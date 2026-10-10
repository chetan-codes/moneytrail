"""Reproducible synthetic records. Runtime must never mount the evaluator directory."""
from __future__ import annotations
import json
import random
import sqlite3
from pathlib import Path

PAYMENT_DATE = '2026-10-09'
REFERENCE = 'PAY-104'
ORGANIZATIONS = ('sender', 'processor', 'recipient')


def _record(scenario, organization, kind, title, amount=None, metadata=None, content=None):
    record = dict(id=f'{scenario}:{organization}:{kind}', organization=organization,
                  kind=kind, reference=REFERENCE, title=title,
                  content=content or title, currency='USD', timestamp=PAYMENT_DATE+'T12:00:00Z',
                  metadata=metadata or {})
    if amount is not None:
        record['amount_minor'] = amount
    return record


def scenario_records(scenario: str) -> list[dict]:
    if scenario not in ('incorrect', 'valid', 'missing'):
        raise ValueError('Unknown scenario')
    result = [
        _record(scenario,'sender','invoice','Invoice INV-104',1000000,content='Invoice INV-104: USD 10,000.00 payable for services.'),
        _record(scenario,'sender','instruction','Payment instruction',1000000,content='Send USD 10,000.00 for invoice INV-104; payment reference PAY-104.'),
        _record(scenario,'sender','debit','Sender bank debit',1000000),
        _record(scenario,'processor','incoming','Processor received payment',1000000),
        _record(scenario,'processor','fee','Processor fee deducted',35000,content='Settlement ledger records a USD 350.00 processing deduction.'),
        _record(scenario,'processor','settlement','Onward settlement',965000),
        _record(scenario,'recipient','credit','Recipient bank credit',965000),
        _record(scenario,'recipient','allocation','Invoice payment allocation',965000,metadata={'invoice':'INV-104'}),
    ]
    if scenario != 'missing':
        fee = 35000 if scenario == 'valid' else 3500
        result.append(_record(scenario,'processor','agreement','Executed fee agreement',metadata={
            'fee_minor':fee, 'effective_date':'2026-09-01','issuer':'processor','authorized':True,
        },content=f'Executed agreement, effective September 1, 2026. For payment PAY-104 the agreed processing fee is USD {fee/100:.2f}. No other deduction is authorized by this agreement.'))
    return result


def make_amendment(scenario: str) -> dict:
    return _record(scenario,'processor','amendment','Signed fee amendment',metadata={
        'fee_minor':35000,'effective_date':'2026-10-01','issuer':'processor','authorized':True,
        'supersedes':f'{scenario}:processor:agreement',
    },content='Signed amendment effective October 1, 2026: the processing fee for PAY-104 is USD 350.00. This replaces the fee in the original agreement.')


def history_records(count: int = 1200, seed: int = 104) -> list[dict]:
    rng = random.Random(seed)
    result=[]
    for i in range(count):
        merchant=f'Counterparty {rng.randrange(1,61):02d}'
        amount=rng.randrange(1000,750000)
        result.append(dict(id=f'history:sender:{i:04d}',organization='sender',kind='debit',
            reference=f'HIST-{i:04d}',title=f'{merchant} · payment {i+1}',
            content=f'Synthetic historical payment to {merchant}.',amount_minor=amount,currency='USD',
            timestamp=f'2026-09-{1+i%28:02d}T12:00:00Z',metadata={'counterparty':merchant,'synthetic':True}))
    return result


def generate(root: Path) -> None:
    root=Path(root)
    records=sum((scenario_records(s) for s in ('incorrect','valid','missing')), [])
    for org in ORGANIZATIONS:
        folder=root/org
        folder.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(folder/'records.sqlite') as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, scenario TEXT, reference TEXT, payload TEXT)')
            rows=[(r['id'],r['id'].split(':')[0],r['reference'],json.dumps(r)) for r in records if r['organization']==org]
            if org=='sender':
                rows.extend((r['id'],'history',r['reference'],json.dumps(r)) for r in history_records())
            db.executemany('INSERT OR REPLACE INTO records VALUES (?,?,?,?)',rows)
    evaluator=root/'evaluator'
    evaluator.mkdir(exist_ok=True)
    (evaluator/'ground_truth.json').write_text(json.dumps({
        'synthetic':True,'seed':104,'payment_date':PAYMENT_DATE,
        'cases':{'incorrect':{'action':'request_correction','amount_minor':31500},
                 'valid':{'action':'close','amount_minor':0},
                 'missing':{'action':'request_evidence','amount_minor':0}},
        'injected_error':'incorrect scenario deducts 35000 cents while agreement permits 3500',
    },indent=2))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    generate(parser.parse_args().root)
