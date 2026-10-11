"""An isolated organization, using the official A2A 0.3 SDK JSON-RPC server."""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapabilities, AgentSkill, DataPart, Part
from a2a.utils import new_agent_parts_message
from starlette.responses import JSONResponse
from .security import validate
from .data import SCENARIOS, make_amendment

ORG = os.environ.get('ORG', 'sender')
DB = Path(os.environ.get('ORG_DB', f'runtime/{ORG}/records.sqlite'))
SECRET = os.environ.get('ORG_SECRET', '')
PORT = {'sender': 8101, 'processor': 8102, 'recipient': 8103}[ORG]


def connect():
    con = sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS amendments (case_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS corrections (key TEXT PRIMARY KEY, case_id TEXT, version INTEGER, amount INTEGER, receipt TEXT)')
    return con


def handle(payload):
    operation = payload.get('operation')
    scenario = payload.get('scenario')
    if scenario not in SCENARIOS or payload.get('reference') != SCENARIOS[scenario][0]:
        raise ValueError('Request outside authorized demo reference')
    case_id = payload.get('case_id', '')
    if not case_id or len(case_id) > 100:
        raise ValueError('Case ID required')
    with connect() as con:
        if operation == 'overview' and ORG == 'sender':
            rows = con.execute("SELECT payload FROM records WHERE scenario='history'").fetchall()
            return {'organization': ORG, 'records': [json.loads(row[0]) for row in rows]}
        if operation == 'retrieve':
            rows = con.execute('SELECT payload FROM records WHERE scenario=? AND reference=?',
                               (scenario, payload['reference'])).fetchall()
            records = [json.loads(row[0]) for row in rows]
            amendment = con.execute('SELECT payload FROM amendments WHERE case_id=?', (case_id,)).fetchone()
            if amendment:
                records.append(json.loads(amendment[0]))
            kind = payload.get('kind')
            if kind == 'documents':
                records = [r for r in records if r['kind'] in ('agreement', 'amendment')]
            elif kind == 'movements':
                records = [r for r in records if r['kind'] not in ('agreement', 'amendment')]
            elif kind not in (None, 'all'):
                raise ValueError('Unknown retrieval skill')
            return {'organization': ORG, 'records': records}
        if ORG != 'processor':
            raise ValueError('Organization does not provide this skill')
        if operation == 'amend':
            record = make_amendment(scenario)
            con.execute('INSERT OR REPLACE INTO amendments VALUES (?,?)', (case_id, json.dumps(record)))
            return {'organization': ORG, 'records': [record]}
        if operation == 'correction':
            amount, version, key = payload.get('amount_minor'), payload.get('version'), payload.get('idempotency_key')
            if type(amount) is not int or not 0 < amount <= SCENARIOS[scenario][2] or type(version) is not int or not key:
                raise ValueError('Invalid correction request')
            existing = con.execute('SELECT case_id,version,amount,receipt FROM corrections WHERE key=?', (key,)).fetchone()
            if existing:
                if tuple(existing[:3]) != (case_id, version, amount):
                    raise ValueError('Idempotency key reused with another action')
                return json.loads(existing[3])
            receipt = {'organization': ORG, 'receipt_id': 'REQ-' + key, 'status': 'requested',
                       'amount_minor': amount, 'currency': 'USD', 'case_id': case_id,
                       'timestamp': datetime.now(timezone.utc).isoformat(),
                       'message': 'Correction request received by simulated processor. Not accepted or settled.'}
            con.execute('INSERT INTO corrections VALUES (?,?,?,?,?)', (key, case_id, version, amount, json.dumps(receipt)))
            return receipt
        raise ValueError('Unknown operation')


class Executor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        try:
            payload = next(p.root.data for p in context.message.parts if isinstance(p.root, DataPart))
            result = handle(payload)
        except (ValueError, StopIteration) as exc:
            result = {'error': str(exc)}
        await event_queue.enqueue_event(new_agent_parts_message([Part(root=DataPart(data=result))]))

    async def cancel(self, context, event_queue):
        raise ValueError('Read requests complete synchronously')


card = AgentCard(name=f'MoneyTrail {ORG}', description='Synthetic evidence retrieval; scoped records only.',
                 url=os.environ.get('PUBLIC_URL', f'http://127.0.0.1:{PORT}/'), version='0.1.0',
                 protocol_version='0.3.0', capabilities=AgentCapabilities(streaming=False),
                 default_input_modes=['application/json'], default_output_modes=['application/json'],
                 skills=[AgentSkill(id='evidence', name='Retrieve payment evidence', description='Retrieve authorized evidence for a case.', tags=['evidence'])])
_sdk_app = A2AStarletteApplication(agent_card=card, http_handler=DefaultRequestHandler(
    agent_executor=Executor(), task_store=InMemoryTaskStore())).build()


class CapabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] == 'GET' and scope['path'].startswith('/.well-known/'):
            return await self.app(scope, receive, send)
        # Only authenticated SendMessage. Do not expose other tasks or arbitrary RPC methods.
        chunks = []
        while True:
            message = await receive()
            chunks.append(message.get('body', b''))
            if sum(map(len, chunks)) > 65536:
                return await JSONResponse({'error': 'Request too large'}, 413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        try:
            request = json.loads(body)
            if request['method'] != 'message/send':
                raise ValueError('Unsupported method')
            payload = next(p['data'] for p in request['params']['message']['parts'] if p.get('kind') == 'data')
            headers = dict(scope['headers'])
            token = headers.get(b'authorization', b'').decode().removeprefix('Bearer ')
            if not SECRET or not validate(token, SECRET, ORG, payload):
                raise ValueError('Unauthorized capability')
        except (ValueError, KeyError, StopIteration, TypeError):
            return await JSONResponse({'error': 'Unauthorized request'}, 403)(scope, receive, send)
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)

app = CapabilityMiddleware(_sdk_app)
