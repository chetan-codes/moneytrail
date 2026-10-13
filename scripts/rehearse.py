"""Rehearse the demo against running services: every case, the amendment twist, an approval.

Run it after any change and before recording. A prompt or data edit can leave the tests green
and still break a live run, which is how a reviewer disagreement once reached the demo path.

Besides the final answer it scores each agent on its own task: what it got right, what it
added that was not needed (false positive) and what it missed (false negative), with timings.
Every round repeats the same six payments, so this measures consistency; scripts/agent_eval.py
measures accuracy on varied payments.

Usage: python scripts/rehearse.py [--rounds 3] [--mode live|deterministic] [--output docs/rehearsal.json]
"""
import argparse
import collections
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.data import make_amendment, scenario_records

API = 'http://127.0.0.1:8000'
REQUIRED = {('sender', 'movements'), ('processor', 'movements'), ('recipient', 'movements'), ('processor', 'documents')}
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


SCORE = collections.defaultdict(collections.Counter)   # agent -> right / extra / missed
SECONDS = collections.defaultdict(list)                # agent -> response times
OUTCOME = collections.Counter()                        # (what was true, what the system said)


def audit(case, scenario, expected, amended=False):
    """Score every agent on the latest investigation of one case."""
    events = case.get('events', [])
    # An amended case logs both investigations; only the latest one is scored.
    events = events[max((i for i, e in enumerate(events) if e['message'].startswith('Amendment added')), default=0):]
    roles = collections.Counter(e['data'].get('role') for e in events if e['type'] == 'model')
    asked = [(e['data']['organization'], e['message'].split()[2]) for e in events if e['type'] == 'request']
    SCORE['manager: evidence requests'].update(right=len(set(asked) & REQUIRED), extra=len(asked) - len(set(asked) & REQUIRED), missed=len(REQUIRED - set(asked)))
    if set(asked) >= REQUIRED:   # an organization can only be scored on what it was asked for
        returned = {r['id'] for r in case['records']}
        for record in scenario_records(scenario) + ([make_amendment(scenario)] if amended else []):
            SCORE[record['organization'] + ' service: records returned'].update(right=record['id'] in returned, missed=record['id'] not in returned)
        for record in case['records']:
            SCORE[record['organization'] + ' service: records returned'].update(extra=record['organization'] + ':' not in record['id'] or record['reference'] != case['reference'])
    if case.get('mode') == 'live':
        documents = [r for r in case['records'] if r['kind'] in ('agreement', 'amendment')]
        if documents:
            # A rejected reading stops the case. On a clean document that is a false alarm; on the injected one the reader was fooled and caught.
            kind = 'injected' if scenario == 'injected' else 'clean'
            SCORE[f'document reader: {kind} documents'].update(right=roles['document verifier'], missed=len(documents) - roles['document verifier'])
        if any(e['type'] == 'finding' for e in events):
            SCORE['reviewer: same result, reached blind'].update(right=roles['resolution reviewer'], missed=1 - roles['resolution reviewer'])
    said = outcome(case)
    truth = 'should close' if expected[0] == 'close' else 'should flag'
    OUTCOME[truth, 'stopped for a human' if said[0] is None else 'closed' if said[0] == 'close' else 'flagged'] += 1
    SCORE['whole system: final answer'].update(right=said == expected, extra=truth == 'should close' and said[0] not in (None, 'close'),
                                               missed=truth == 'should flag' and said[0] == 'close')
    stamps = [datetime.fromisoformat(e['timestamp']) for e in events]
    for i in range(1, len(events)):
        gap, before, event = (stamps[i] - stamps[i - 1]).total_seconds(), events[i - 1], events[i]
        if before['type'] == 'request':
            SECONDS[before['data']['organization'] + ' service: records returned'].append(gap)
        elif event['type'] == 'model' and event['data']['role'] == 'manager' and before['type'] == 'status':
            SECONDS['manager: evidence requests'].append(gap)   # first decision only; later rounds are not timed
        elif event['type'] == 'model' and event['data']['role'] == 'document verifier':
            SECONDS[f"document reader: {'injected' if scenario == 'injected' else 'clean'} documents"].append(gap)
        elif event['type'] == 'model' and event['data']['role'] == 'resolution reviewer':
            SECONDS['reviewer: same result, reached blind'].append(gap)
    if case.get('metrics', {}).get('elapsed_seconds'):
        SECONDS['whole system: final answer'].append(case['metrics']['elapsed_seconds'])


def report():
    rows = []
    print(f"\n{'agent and task':<44}{'right':>10}{'extra':>7}{'missed':>8}{'median s':>10}{'slowest s':>11}")
    for agent in sorted(SCORE, key=lambda a: ('whole' in a, 'reviewer' in a, 'reader' in a, 'service' in a, a)):
        score, times = SCORE[agent], SECONDS[agent]
        total = score['right'] + score['missed']
        rows.append(dict(agent=agent, right=score['right'], of=total, extra=score['extra'], missed=score['missed'],
                         median_seconds=round(statistics.median(times), 3) if times else None, slowest_seconds=round(max(times), 3) if times else None))
        print(f"{agent:<44}{str(score['right']) + '/' + str(total):>10}{score['extra']:>7}{score['missed']:>8}"
              f"{rows[-1]['median_seconds'] or '':>10}{rows[-1]['slowest_seconds'] or '':>11}")
    print('\nfinal answers, what was true against what the system said')
    for truth in ('should close', 'should flag'):
        print(f"  {truth:<14}" + '  '.join(f'{said} {OUTCOME[truth, said]}' for said in ('closed', 'flagged', 'stopped for a human')))
    print(f"  false positives (flagged a payment that was fine): {OUTCOME['should close', 'flagged']}"
          f"   false negatives (closed a payment that was not): {OUTCOME['should flag', 'closed']}")
    return dict(agents=rows, outcomes={f'{truth} -> {said}': count for (truth, said), count in sorted(OUTCOME.items())},
                false_positives=OUTCOME['should close', 'flagged'], false_negatives=OUTCOME['should flag', 'closed'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--mode', default='live', choices=('live', 'deterministic'))
    parser.add_argument('--output', type=Path)
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
            audit(case, scenario, expected)
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
            if 'id' in amended:
                audit(amended, scenario, ('close', 0), amended=True)

    print(f'\n{sum(results)}/{len(results)} passed ({args.mode} mode)')
    summary = dict(mode=args.mode, rounds=args.rounds, checks=len(results), passed=sum(results), **report())
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2) + '\n')
    sys.exit(0 if all(results) else 1)
