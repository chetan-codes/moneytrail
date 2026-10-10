"""Run MoneyTrail's deterministic verifier against FinRCA-Bench (arXiv 2608.18534, MIT).

This is an out-of-domain generalization probe, not a leaderboard entry. FinRCA asks for a
16-class root cause over 14 accounts-payable tables; MoneyTrail decides one of three
operational dispositions over a single payment trail. The point is to measure how the
verifier behaves on data it was not built for, under FinRCA's oracle-retrieval condition
(the benchmark's own per-case evidence bundle is supplied, so retrieval is not being tested).

Usage: python scripts/finrca_eval.py /path/to/FinRCA-AI-Bench [--output report.json]
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.verify import verify

SPLITS = ('train', 'test', 'validation', 'challenge_test')
# FinRCA table -> (MoneyTrail kind, owning organization, amount column). Tables absent here
# have no MoneyTrail analogue and are reported as unmapped rather than coerced into one.
MAPPING = {
    'payments': ('debit', 'sender', 'payment_amount'),
    'bank_transactions': ('credit', 'recipient', 'amount'),
    'invoices': ('invoice', 'sender', 'invoice_total'),
    'payment_allocations': ('allocation', 'recipient', 'allocated_amount'),
}
KEY = {'payments': 'payment_id', 'bank_transactions': 'bank_transaction_id',
       'invoices': 'invoice_id', 'payment_allocations': 'payment_id'}
DATE = {'payments': 'payment_date', 'bank_transactions': 'transaction_date',
        'invoices': 'invoice_date', 'payment_allocations': 'allocation_date'}


def minor(value):
    try:
        return int((Decimal(str(value)) * 100).to_integral_value())
    except (InvalidOperation, TypeError, ValueError):
        return None


def to_evidence(case_id, table, record, seen):
    kind, organization, amount_column = MAPPING[table]
    identifier = str(record.get(KEY[table]) or '')
    if not identifier or identifier in seen:
        return None
    seen.add(identifier)
    amount = minor(record.get(amount_column))
    if amount is None:
        return None
    date = str(record.get(DATE[table]) or '2026-01-01')[:10]
    return dict(id=identifier, organization=organization, kind=kind, reference=case_id,
                title=f'{table} {identifier}', content=f'{table} {identifier} records {amount/100:,.2f} USD.',
                amount_minor=abs(amount), currency=str(record.get('currency') or 'USD'),
                timestamp=f'{date}T00:00:00+00:00', metadata={'table': table})


def load(root: Path):
    manifest = {}
    for split in SPLITS:
        path = root / 'data' / 'benchmark' / split / 'failure_manifest.csv'
        if path.exists():
            for row in csv.DictReader(path.open()):
                manifest[row['case_id']] = row
    bundles = defaultdict(list)
    for split in SPLITS:
        path = root / 'data' / 'benchmark' / split / 'case_entity_records.jsonl'
        if path.exists():
            for line in path.open():
                row = json.loads(line)
                bundles[row['case_id']].append(row)
    return manifest, bundles


def run(root: Path):
    manifest, bundles = load(root)
    rows = []
    for case_id, entries in sorted(bundles.items()):
        meta = manifest.get(case_id)
        if not meta:
            continue
        seen = set()
        records = [e for e in (to_evidence(case_id, r['table'], r['record'], seen)
                               for r in entries if r['table'] in MAPPING) if e]
        unmapped = sum(1 for r in entries if r['table'] not in MAPPING)
        result = verify(records)
        action = result['recommendation']['action']
        rows.append(dict(case_id=case_id, failure_type=meta['failure_type'], split=meta['split'],
                         has_failure=meta['failure_type'] != 'NO_FAILURE',
                         flagged=action != 'close', action=action,
                         reason=result['findings'][-1]['title'] if result['findings'] else 'none',
                         mapped_records=len(records), unmapped_records=unmapped))
    return rows


def summarize(rows):
    failures = [r for r in rows if r['has_failure']]
    clean = [r for r in rows if not r['has_failure']]
    tp = sum(r['flagged'] for r in failures)
    fp = sum(r['flagged'] for r in clean)
    reasons = Counter(r['reason'] for r in rows)
    by_type = defaultdict(lambda: Counter())
    for r in rows:
        by_type[r['failure_type']][r['action']] += 1
    # A detector that flags everything scores perfect recall and zero precision; report both
    # plus the share of clean cases it also flags, so the degenerate case cannot hide.
    return dict(
        condition='oracle retrieval; FinRCA per-case evidence bundle supplied, retrieval not tested',
        task_mismatch='FinRCA labels 16 root causes over 14 AP tables; MoneyTrail returns one of three dispositions over one payment trail',
        cases=len(rows), with_failure=len(failures), without_failure=len(clean),
        flagged_failures=tp, flagged_clean=fp,
        recall=round(tp / len(failures), 4) if failures else None,
        precision=round(tp / (tp + fp), 4) if (tp + fp) else None,
        false_positive_rate=round(fp / len(clean), 4) if clean else None,
        discriminates=bool(failures and clean and (tp / len(failures)) != (fp / len(clean))),
        mapped_records_total=sum(r['mapped_records'] for r in rows),
        unmapped_records_total=sum(r['unmapped_records'] for r in rows),
        actions=dict(Counter(r['action'] for r in rows)),
        verifier_reasons=dict(reasons.most_common()),
        by_failure_type={k: dict(v) for k, v in sorted(by_type.items())})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path, help='clone of PratikGhawate/FinRCA-AI-Bench')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    rows = run(args.root)
    if not rows:
        raise SystemExit('No cases found; check the benchmark path.')
    report = dict(benchmark='FinRCA-Bench (arXiv 2608.18534), MIT', **summarize(rows), results=rows)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}, indent=2))
