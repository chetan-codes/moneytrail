"""Rehearse the demo against running services: every case, the amendment twist, an approval.

Run it after any change and before recording. A prompt or data edit can leave the tests green
and still break a live run, which is how a reviewer disagreement once reached the demo path.

Usage: python scripts/rehearse.py [--rounds 3] [--mode live|deterministic]
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = 'http://127.0.0.1:8000'
# The evaluator's answer key, written by scripts/run.py; the services never read it.
TRUTH = json.loads((Path(__file__).resolve().parents[1] / 'runtime' / 'evaluator' / 'ground_truth.json').read_text())['cases']
EXPECTED = {name: (case['action'], case['amount_minor']) for name, case in TRUTH.items()}


def call(path, body=None):
    request = urllib.request.Request(API + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    try:
        return json.load(urllib.request.urlopen(request, timeout=60))
    except urllib.error.HTTPError as error:
        return {'http_error': error.code, 'detail': error.read().decode()[:200]}


def settle(case):
    for _ in range(150):
        case = call('/cases/' + case['id'])
        if case.get('status') not in ('created', 'investigating'):
            return case
        time.sleep(.4)
    return case


def outcome(case):
    recommendation = case.get('recommendation') or {}
    return recommendation.get('action'), recommendation.get('amount_minor')


def errors(case):
    return [event['message'] for event in case.get('events', []) if event['type'] == 'error']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--mode', default='live', choices=('live', 'deterministic'))
    args = parser.parse_args()
    results = []

    def check(label, passed, case, started):
        results.append(passed)
        print(f"{'PASS' if passed else 'FAIL'}  {label:<34} {str(outcome(case)):<32} {time.time() - started:4.1f}s  {errors(case)[:1] or ''}", flush=True)

    for round_number in range(1, args.rounds + 1):
        for scenario, expected in EXPECTED.items():
            started = time.time()
            case = settle(call('/cases', {'scenario': scenario, 'mode': args.mode}))
            # With a live model an injected document may fool the reader; the cross-check then
            # withholds any recommendation. That is the designed outcome, never a wrong one.
            escalated = scenario == 'injected' and args.mode == 'live' and not case.get('recommendation') and bool(errors(case))
            check(f'round {round_number} {scenario}' + (' (escalated to a human)' if escalated else ''), outcome(case) == expected or escalated, case, started)
            if expected[0] == 'request_correction' and outcome(case) == expected:
                started = time.time()
                key = f"{case['id']}-{case['version']}-request_correction"
                approved = call(f"/cases/{case['id']}/approve", {'version': case['version'], 'action': 'request_correction', 'idempotency_key': key})
                check(f'round {round_number} {scenario} approve', approved.get('case', {}).get('status') == 'approved', approved.get('case', case), started)
        for scenario in ('incorrect', 'wire'):
            started = time.time()
            case = settle(call('/cases', {'scenario': scenario, 'mode': args.mode}))
            amended = call(f"/cases/{case['id']}/evidence", {'version': case.get('version'), 'amendment': 'permit_350'})
            amended = settle(amended) if 'id' in amended else amended
            check(f'round {round_number} {scenario} + amendment -> close', outcome(amended) == ('close', 0) and amended.get('version') == 2, amended if 'id' in amended else case, started)

    print(f'\n{sum(results)}/{len(results)} passed ({args.mode} mode)')
    sys.exit(0 if all(results) else 1)
