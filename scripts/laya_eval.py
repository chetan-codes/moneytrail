"""Score a Laya checkpoint on a split from scripts/laya_dataset.py.

Reports AUC, accuracy and the clean/injected means. AUC is the number that matters: it is
threshold-free, so an improvement cannot come from calibration alone.

Usage: python scripts/laya_eval.py data/laya/test.jsonl [--model DIR] [--output report.json]
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
os.environ.setdefault('USE_TF', '0')


def value(answer):
    if isinstance(answer, dict):
        return answer.get('noul', answer.get('probability'))
    return getattr(answer, 'noul', None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('data', type=Path)
    parser.add_argument('--model', default=None, help='local checkpoint dir; default is the published base model')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()

    import laya
    agent = laya.load(args.model) if args.model else laya.load('convaiinnovations/laya')
    rows = [json.loads(l) for l in args.data.open()]
    if args.limit:
        rows = rows[:args.limit]
    scored, latencies = [], []
    for row in rows:
        start = time.time()
        result = agent.predict(row['state'], row['questions'])
        latencies.append((time.time() - start) * 1000)
        answers = result['answers'] if isinstance(result, dict) else result.answers
        probability = value(answers['has_instruction'])
        if isinstance(probability, (int, float)):
            scored.append((bool(row['expected']['has_instruction']), float(probability), row.get('family'), row.get('injection')))
    injected = [p for t, p, *_ in scored if t]
    clean = [p for t, p, *_ in scored if not t]
    pairs = [(a, b) for a in injected for b in clean]
    auc = sum((a > b) + 0.5 * (a == b) for a, b in pairs) / len(pairs) if pairs else None
    accuracy = sum((p >= .5) == t for t, p, *_ in scored) / len(scored) if scored else None
    report = dict(model=args.model or 'convaiinnovations/laya (base)', data=str(args.data), scored=len(scored),
                  auc=round(auc, 4) if auc else None, accuracy=round(accuracy, 4) if accuracy else None,
                  clean_mean=round(sum(clean) / len(clean), 4) if clean else None,
                  injected_mean=round(sum(injected) / len(injected), 4) if injected else None,
                  median_latency_ms=round(sorted(latencies)[len(latencies) // 2], 1) if latencies else None)
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(report, scores=[[t, p, f, i] for t, p, f, i in scored]), indent=2))


if __name__ == '__main__':
    main()
