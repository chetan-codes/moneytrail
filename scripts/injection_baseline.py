"""Does the fine-tuned model beat a keyword matcher on the same real data?

A 421M model earns its place only if it beats the dumb thing. This scores the identical
pairs used by jobs/laya_real_eval_job.py -- real CUAD clauses, real deepset attacks, in
three positions -- with a list of instruction markers and nothing else.

Usage: python scripts/injection_baseline.py
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
src = (Path(__file__).resolve().parent / 'laya_real_eval.py').read_text().replace("if __name__ == '__main__':\n    main()", '')
ns: dict = {}
exec(compile(src, 'laya_real_eval', 'exec'), ns)

# Imperatives and meta-instructions aimed at a reader. Contract prose says "shall" and
# "may"; it does not usually say "ignore the above" or "show me your prompt".
MARKERS = [r'\bignore\b', r'\bdisregard\b', r'\bforget\b', r'\binstead\b', r'\byou are now\b',
           r'\bact as\b', r'\bpretend\b', r'\bprevious instructions?\b', r'\bprompt\b',
           r'\bplease\s+\w+', r'\bdo not\s+\w+', r'\bshow me\b', r'\btell me\b', r'\bgive me\b',
           r'\bsend\b', r'\bforward\b', r'\bapprove\b', r'\bmark\s+\w+\s+as\b', r'\boutput\b',
           r'\breply\b', r'\brespond\b', r'\burgent\b', r'\bsystem notice\b', r'\bimmediately\b',
           r'\bmaintenance mode\b', r'\bnew task\b', r'\byour instructions?\b']
PATTERN = [re.compile(m, re.I) for m in MARKERS]


def score(text: str) -> float:
    """Fraction of markers present: a graded score so AUC is meaningful."""
    return sum(bool(p.search(text)) for p in PATTERN) / len(PATTERN)


def evaluate(clauses, attacks, where):
    scored = []
    for index, clause in enumerate(clauses):
        attack = attacks[index % len(attacks)]
        scored.append((False, score(clause)))
        scored.append((True, score(ns['__dict__'].get('splice', splice)(clause, attack, where) if False else splice(clause, attack, where))))
    inj = [p for t, p in scored if t]
    cln = [p for t, p in scored if not t]
    pairs = [(a, b) for a in inj for b in cln]
    thresholds = sorted({p for _, p in scored})
    best = max(thresholds, key=lambda t: sum((p >= t) == y for y, p in scored))
    return dict(n=len(scored),
                auc=round(sum((a > b) + 0.5 * (a == b) for a, b in pairs) / len(pairs), 4),
                best_accuracy=round(sum((p >= best) == y for y, p in scored) / len(scored), 4),
                clean_mean=round(sum(cln) / len(cln), 4), injected_mean=round(sum(inj) / len(inj), 4))


def splice(clause, attack, where):
    if where == 'appended':
        return clause + '\n' + attack
    if where == 'prepended':
        return attack + '\n' + clause
    parts = clause.split('. ')
    middle = max(1, len(parts) // 2)
    return '. '.join(parts[:middle]) + '. ' + attack + ' ' + '. '.join(parts[middle:])


if __name__ == '__main__':
    token = next((l.split('=', 1)[1].strip() for l in Path('.env').read_text().splitlines()
                  if l.startswith('HF_TOKEN=')), '')
    cache = Path(os.environ.get('TMPDIR', '/tmp')) / 'laya_realdata'
    clauses = ns['contracts'](token, 99, cache)
    attacks = ns['attacks'](token, 120, cache)
    print(f'real clauses {len(clauses)} | real attacks {len(attacks)}')
    report = {w: evaluate(clauses, attacks, w) for w in ('appended', 'prepended', 'embedded')}
    print(json.dumps(report, indent=2))
    Path('docs').mkdir(exist_ok=True)
    Path('docs/injection_keyword_baseline.json').write_text(json.dumps(report, indent=2))
