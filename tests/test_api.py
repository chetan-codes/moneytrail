"""Service integration tests with scoped in-process transport, never external inference."""
import asyncio
import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from backend.data import generate, make_amendment, scenario_records
from backend.security import issue, validate
api = importlib.import_module('backend.app')
org = importlib.import_module('backend.org_service')


class CaseApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.amendments=set()
        self.corrections=[]
        self.requests=[]
        api.CASES.clear();api.TASKS.clear();api.LOCKS.clear()
        self.state=patch.object(api,'STATE',Path(self.tmp.name));self.state.start()
        self.transport=patch.object(api.transport,'request',side_effect=self.request);self.transport.start()
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://test')

    async def asyncTearDown(self):
        for task in api.TASKS.values():
            if not task.done():task.cancel()
        await asyncio.gather(*api.TASKS.values(),return_exceptions=True)
        await self.client.aclose()
        self.transport.stop();self.state.stop();self.tmp.cleanup()

    async def request(self,organization,payload):
        self.requests.append((organization,copy.deepcopy(payload)))
        case_id=payload['case_id']
        if payload['operation']=='amend':
            self.amendments.add(case_id)
            return {'records':[make_amendment(payload['scenario'])]}
        if payload['operation']=='correction':
            self.corrections.append(copy.deepcopy(payload))
            return {'status':'requested','message':'Correction requested; not settled.'}
        records=[r for r in scenario_records(payload['scenario']) if r['organization']==organization]
        if organization=='processor' and case_id in self.amendments:
            records.append(make_amendment(payload['scenario']))
        kind=payload.get('kind')
        if kind=='documents':records=[r for r in records if r['kind'] in ('agreement','amendment')]
        if kind=='movements':records=[r for r in records if r['kind'] not in ('agreement','amendment')]
        return {'records':records}

    async def create(self,scenario='incorrect'):
        response=await self.client.post('/cases',json={'scenario':scenario,'mode':'deterministic'})
        self.assertEqual(response.status_code,200,response.text)
        cid=response.json()['id']
        await api.TASKS[cid]
        return (await self.client.get('/cases/'+cid)).json()

    async def test_three_demo_cases_three_rehearsals(self):
        for _ in range(3):
            for scenario,action in [('incorrect','request_correction'),('valid','close'),('missing','request_evidence')]:
                case=await self.create(scenario)
                self.assertEqual(case['recommendation']['action'],action)
                self.assertEqual(case['mode'],'deterministic')
                known={r['id'] for r in case['records']}
                evidence_nodes=[n for n in case['graph']['nodes'] if n.get('evidence_id')]
                self.assertTrue(all(n['evidence_id'] in known for n in evidence_nodes))
                self.assertEqual(len(known),len(case['records']))

    async def test_stale_approval_rejected(self):
        case=await self.create()
        response=await self.client.post(f'/cases/{case["id"]}/approve',json={
            'version':0,'action':'request_correction','idempotency_key':'approve-0001'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.corrections,[])

    async def test_duplicate_approval_one_processor_request(self):
        case=await self.create()
        body={'version':1,'action':'request_correction','idempotency_key':'approve-0001'}
        one=await self.client.post(f'/cases/{case["id"]}/approve',json=body)
        two=await self.client.post(f'/cases/{case["id"]}/approve',json=body)
        self.assertEqual(one.status_code,200,one.text)
        self.assertEqual(two.status_code,200,two.text)
        self.assertEqual(one.json()['approval'],two.json()['approval'])
        self.assertEqual(len(self.corrections),1)
        self.assertEqual(self.corrections[0]['amount_minor'],31500)
        conflict=await self.client.post(f'/cases/{case["id"]}/approve',json={**body,'idempotency_key':'other-key'})
        self.assertEqual(conflict.status_code,409)

    async def test_amendment_invalidates_recommendation_and_stale_action(self):
        case=await self.create();cid=case['id']
        response=await self.client.post(f'/cases/{cid}/evidence',json={'version':1,'amendment':'permit_350'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['version'],2)
        self.assertIsNone(response.json()['recommendation'])
        await api.TASKS[cid]
        updated=(await self.client.get(f'/cases/{cid}')).json()
        self.assertEqual(updated['recommendation']['action'],'close')
        self.assertEqual(updated['unsupported_minor'],0)
        stale=await self.client.post(f'/cases/{cid}/approve',json={
            'version':1,'action':'request_correction','idempotency_key':'approve-0001'})
        self.assertEqual(stale.status_code,409)
        wrongaction=await self.client.post(f'/cases/{cid}/approve',json={
            'version':2,'action':'request_correction','idempotency_key':'approve-0002'})
        self.assertEqual(wrongaction.status_code,409)
        self.assertEqual(self.corrections,[])

    async def test_sse_cursor_has_no_duplicate_events(self):
        case=await self.create();cid=case['id']
        response=await self.client.get(f'/cases/{cid}/events?after=2',headers={'Last-Event-ID':'5'})
        self.assertEqual(response.status_code,200)
        messages=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        seq=[m['seq'] for m in messages]
        self.assertEqual(seq,list(range(6,len(case['events'])+1)))
        self.assertEqual(len(seq),len(set(seq)))
        end=await self.client.get(f'/cases/{cid}/events',headers={'Last-Event-ID':str(len(case['events']))})
        self.assertNotIn('data:',end.text)
        malformed=await self.client.get(f'/cases/{cid}/events',headers={'Last-Event-ID':'bad'})
        self.assertEqual(malformed.status_code,400)

    async def test_unconfigured_live_rejected_without_fallback(self):
        with patch.object(api.model,'configuration',return_value={'model_configured':False}):
            response=await self.client.post('/cases',json={'scenario':'incorrect','mode':'live'})
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.requests,[])
        self.assertEqual(api.CASES,{})

    async def test_failed_live_model_has_no_deterministic_fallback(self):
        with patch.object(api.model,'configuration',return_value={'model_configured':True}),patch.object(api.model,'complete',new=AsyncMock(side_effect=RuntimeError('Model unavailable'))):
            response=await self.client.post('/cases',json={'scenario':'incorrect','mode':'live'})
            self.assertEqual(response.status_code,200)
            cid=response.json()['id'];await api.TASKS[cid]
        case=(await self.client.get('/cases/'+cid)).json()
        self.assertEqual(case['mode'],'live')
        self.assertEqual(case['status'],'incomplete')
        self.assertIsNone(case['recommendation'])
        self.assertEqual(self.requests,[])
        self.assertTrue(any(e['type']=='error' for e in case['events']))


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.payload={'operation':'retrieve','case_id':'case-1','scenario':'incorrect','reference':'PAY-104','kind':'all'}

    def test_hmac_tamper_wrong_org_wrong_body_expiry(self):
        token=issue('secret','processor',self.payload)
        self.assertTrue(validate(token,'secret','processor',self.payload))
        self.assertFalse(validate(token,'wrong','processor',self.payload))
        self.assertFalse(validate(token,'secret','recipient',self.payload))
        self.assertFalse(validate(token,'secret','processor',{**self.payload,'reference':'OTHER'}))
        self.assertFalse(validate(token[:-1]+('0' if token[-1]!='0' else '1'),'secret','processor',self.payload))
        self.assertFalse(validate(issue('secret','processor',self.payload,ttl=-10),'secret','processor',self.payload))
        for malformed in ('','bad','@@@.bad','one.two.three'):
            self.assertFalse(validate(malformed,'secret','processor',self.payload))

    def test_organization_scope_and_processor_idempotency(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);generate(root)
            for organization in ('sender','processor','recipient'):
                with patch.object(org,'ORG',organization),patch.object(org,'DB',root/organization/'records.sqlite'):
                    result=org.handle(self.payload)
                    self.assertTrue(result['records'])
                    self.assertTrue(all(r['organization']==organization for r in result['records']))
                    self.assertTrue(all(r['reference']=='PAY-104' for r in result['records']))
                    for bad in ({'reference':'OTHER'},{'scenario':'history'},{'kind':'SELECT * FROM records'}):
                        with self.assertRaises(ValueError):org.handle({**self.payload,**bad})
                    if organization!='processor':
                        with self.assertRaises(ValueError):org.handle({**self.payload,'operation':'amend'})
            with patch.object(org,'ORG','processor'),patch.object(org,'DB',root/'processor'/'records.sqlite'):
                correction={**self.payload,'operation':'correction','version':1,'amount_minor':31500,'idempotency_key':'key-1'}
                first=org.handle(correction);second=org.handle(correction)
                self.assertEqual(first,second)
                self.assertEqual(first['status'],'requested')
                with self.assertRaises(ValueError):org.handle({**correction,'amount_minor':31400})
                org.handle({**self.payload,'operation':'amend'})
                unrelated=org.handle({**self.payload,'case_id':'another-case'})
                self.assertFalse(any(r['kind']=='amendment' for r in unrelated['records']))


class OrganizationMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_or_tampered_capability_blocked_before_execution(self):
        calls=[]
        async def downstream(scope,receive,send):
            calls.append(True)
            raise AssertionError('Unauthorized request reached organization')
        middleware=org.CapabilityMiddleware(downstream)
        payload={'operation':'retrieve','case_id':'case-1','scenario':'incorrect','reference':'PAY-104'}
        body={'jsonrpc':'2.0','id':'request-1','method':'message/send','params':{'message':{'parts':[{'kind':'data','data':payload}]}}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=middleware),base_url='http://org') as client:
            with patch.object(org,'SECRET','secret'),patch.object(org,'ORG','processor'):
                missing=await client.post('/',json=body)
                self.assertEqual(missing.status_code,403)
                wrongorg=await client.post('/',json=body,headers={'Authorization':'Bearer '+issue('secret','sender',payload)})
                self.assertEqual(wrongorg.status_code,403)
        self.assertEqual(calls,[])
