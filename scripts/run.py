#!/usr/bin/env python3
"""Run local demo processes; use Docker Compose for filesystem mount isolation."""
import argparse
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from backend.data import generate

parser=argparse.ArgumentParser()
parser.add_argument('--no-frontend',action='store_true')
args=parser.parse_args()
generate(ROOT/'runtime')
processes=[]
secrets_by_org={org:secrets.token_hex(32) for org in ('sender','processor','recipient')}
base=os.environ.copy()
try:
    for org,port in [('sender',8101),('processor',8102),('recipient',8103)]:
        env={**base,'ORG':org,'ORG_DB':str(ROOT/'runtime'/org/'records.sqlite'),'ORG_SECRET':secrets_by_org[org]}
        # Organization services never receive HF tokens or other organizations' capability keys.
        for key in ('HF_TOKEN','HF_ENDPOINT','SENDER_SECRET','PROCESSOR_SECRET','RECIPIENT_SECRET'):
            env.pop(key,None)
        processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','backend.org_service:app','--host','127.0.0.1','--port',str(port)],env=env))
    env={**base,'STATE_DIR':str(ROOT/'runtime/coordinator'),**{org.upper()+'_SECRET':value for org,value in secrets_by_org.items()}}
    processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8000'],env=env))
    if not args.no_frontend:
        # Vite 6 needs Node 18+; on an older one it dies with an unrelated crypto error.
        node=subprocess.run(['node','-v'],capture_output=True,text=True).stdout.strip()
        if int(node.lstrip('v').split('.')[0] or 0)<18:
            raise SystemExit(f'Node {node} is too old for the dashboard; Vite needs 18+. Run `nvm use 22` (or omit --no-frontend).')
        processes.append(subprocess.Popen(['npm','run','dev','--','--host','127.0.0.1'],cwd=ROOT/'frontend',env=base))
    print('\nMoneyTrail: http://127.0.0.1:5173 | API: http://127.0.0.1:8000/docs\nSynthetic organizations. Local processes share OS-user privileges; use Compose for mount isolation.\n',flush=True)
    while all(p.poll() is None for p in processes):time.sleep(.5)
finally:
    for p in processes:
        if p.poll() is None:p.terminate()
    for p in processes:
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill()
