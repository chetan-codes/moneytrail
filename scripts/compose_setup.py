"""Generate demo data and missing local secrets. Does not overwrite existing credentials."""
import os
import secrets
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from backend.data import generate
from dotenv import dotenv_values,set_key
generate(root/'runtime')
(root/'runtime/coordinator').mkdir(exist_ok=True)
env=root/'.env'
if not env.exists():env.write_text((root/'.env.example').read_text())
values=dotenv_values(env)
for key in ('SENDER_SECRET','PROCESSOR_SECRET','RECIPIENT_SECRET'):
    if not values.get(key):set_key(str(env),key,secrets.token_hex(32))
# Local demo bind mounts must be writable by the non-root container user.
for name in ('sender','processor','recipient','coordinator'):
    folder=root/'runtime'/name
    os.chmod(folder,0o777)
    for file in folder.glob('*.sqlite'):os.chmod(file,0o666)
os.chmod(env,0o600)
print('Synthetic data and local secrets ready. docker compose up --build')
