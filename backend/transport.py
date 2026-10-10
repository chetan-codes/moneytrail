import asyncio
import os
import uuid
import httpx
from .security import issue


async def request(organization, payload):
    url = os.environ.get(f'{organization.upper()}_URL', f'http://127.0.0.1:{ {"sender":8101,"processor":8102,"recipient":8103}[organization]}/')
    secret = os.environ.get(f'{organization.upper()}_SECRET', '')
    if not secret:
        raise RuntimeError(f'{organization} capability secret missing; use scripts/run.py')
    rpc = {'jsonrpc': '2.0', 'id': str(uuid.uuid4()), 'method': 'message/send', 'params': {
        'message': {'kind': 'message', 'role': 'user', 'messageId': str(uuid.uuid4()),
                    'parts': [{'kind': 'data', 'data': payload}]}}}
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, json=rpc, headers={'Authorization': 'Bearer ' + issue(secret, organization, payload)})
                response.raise_for_status()
                result = response.json()
            if 'error' in result:
                raise RuntimeError('A2A service returned an error')
            parts = result['result'].get('parts', [])
            data = next(p['data'] for p in parts if p.get('kind') == 'data')
            if data.get('error'):
                raise RuntimeError(data['error'])
            return data
        except (httpx.TimeoutException, httpx.ConnectError):
            if attempt:
                raise RuntimeError(f'{organization} unavailable after one retry') from None
            await asyncio.sleep(.3)
