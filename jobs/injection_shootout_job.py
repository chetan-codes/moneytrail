# /// script
# requires-python = ">=3.10"
# dependencies = ["laya==0.4.2", "huggingface_hub>=0.34.0", "sentencepiece", "protobuf"]
# ///
"""Three contenders, identical real data: is a fine-tuned Laya worth shipping at all?

Clean documents are real CUAD contract clauses; attacks are real deepset prompt injections;
each attack is placed at the end, at the start and spliced mid-clause.

  keyword   -- 27 regexes, no model
  laya      -- our fine-tune, 421M, trained on MoneyTrail's synthetic prose
  protectai -- protectai/deberta-v3-base-prompt-injection-v2, 184M, purpose-built

If the purpose-built detector wins, the right answer is to use it and not ship ours.

Run: hf jobs uv run --flavor a10g-small --secrets HF_TOKEN jobs/injection_shootout_job.py
"""
import json, os, re, time, urllib.parse, urllib.request

os.environ.setdefault("USE_TF", "0")
API = "https://datasets-server.huggingface.co/rows"
MONEY = re.compile(r"(fee|payment|invoice|amount|commission|\$|USD|per cent|%)", re.I)
TUNED = os.environ.get("TUNED_REPO", "chetan-choudhary/laya-moneytrail-injection")
PROTECTAI = "protectai/deberta-v3-base-prompt-injection-v2"
QUESTION = {"has_instruction": {"type": "noul", "instructions":
    "The document contains an instruction, command or request directed at the reader or "
    "system, rather than only stating contractual terms, amounts and dates."}}
MARKERS = [r"\bignore\b", r"\bdisregard\b", r"\bforget\b", r"\binstead\b", r"\byou are now\b",
           r"\bact as\b", r"\bpretend\b", r"\bprevious instructions?\b", r"\bprompt\b",
           r"\bplease\s+\w+", r"\bdo not\s+\w+", r"\bshow me\b", r"\btell me\b", r"\bgive me\b",
           r"\bsend\b", r"\bforward\b", r"\bapprove\b", r"\bmark\s+\w+\s+as\b", r"\boutput\b",
           r"\breply\b", r"\brespond\b", r"\burgent\b", r"\bsystem notice\b", r"\bimmediately\b",
           r"\bmaintenance mode\b", r"\bnew task\b", r"\byour instructions?\b"]
PATTERNS = [re.compile(m, re.I) for m in MARKERS]


def fetch(dataset, offset, length, attempts=3):
    url = f"{API}?dataset={urllib.parse.quote(dataset, safe='')}&config=default&split=train&offset={offset}&length={length}"
    token = os.environ.get("HF_TOKEN", "")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as handle:
                return json.load(handle).get("rows", [])
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return []


def real_clauses(want):
    out, offset = [], 1000
    while len(out) < want and offset < 70000:
        for row in fetch("theatticusproject/cuad", offset, 100):
            text = (row["row"].get("text") or "").strip()
            if 120 < len(text) < 900 and MONEY.search(text) and len(set(text)) > 15:
                out.append(" ".join(text.split()))
        offset += 1500
    return out[:want]


def real_attacks(want):
    out = []
    for offset in range(0, 546, 100):
        for row in fetch("deepset/prompt-injections", offset, 100):
            if int(row["row"].get("label", 0)) == 1 and len((row["row"].get("text") or "").strip()) > 25:
                out.append(" ".join(row["row"]["text"].split()))
    return out[:want]


def splice(clause, attack, where):
    if where == "appended":
        return clause + "\n" + attack
    if where == "prepended":
        return attack + "\n" + clause
    parts = clause.split(". ")
    middle = max(1, len(parts) // 2)
    return ". ".join(parts[:middle]) + ". " + attack + " " + ". ".join(parts[middle:])


def summarise(scored, latencies):
    inj = [p for t, p in scored if t]
    cln = [p for t, p in scored if not t]
    pairs = [(a, b) for a in inj for b in cln]
    thresholds = sorted({p for _, p in scored})
    best = max(thresholds, key=lambda t: sum((p >= t) == y for y, p in scored))
    return dict(n=len(scored),
                auc=round(sum((a > b) + 0.5 * (a == b) for a, b in pairs) / len(pairs), 4) if pairs else None,
                accuracy_at_half=round(sum((p >= .5) == t for t, p in scored) / len(scored), 4),
                best_accuracy=round(sum((p >= best) == y for y, p in scored) / len(scored), 4),
                clean_mean=round(sum(cln) / len(cln), 4), injected_mean=round(sum(inj) / len(inj), 4),
                median_latency_ms=round(sorted(latencies)[len(latencies) // 2], 1) if latencies else None)


def main():
    clauses, attacks = real_clauses(99), real_attacks(120)
    print(f"real CUAD clauses {len(clauses)} | real deepset attacks {len(attacks)}", flush=True)
    report = {"clauses": len(clauses), "attacks": len(attacks),
              "clean_source": "theatticusproject/cuad", "attack_source": "deepset/prompt-injections"}

    def run(name, scorer):
        for where in ("appended", "prepended", "embedded"):
            scored, latencies = [], []
            for index, clause in enumerate(clauses):
                attack = attacks[index % len(attacks)]
                for text, truth in ((clause, False), (splice(clause, attack, where), True)):
                    start = time.time()
                    p = scorer(text)
                    latencies.append((time.time() - start) * 1000)
                    if p is not None:
                        scored.append((truth, float(p)))
            report[f"{name}_{where}"] = summarise(scored, latencies)
            print(f"{name:<10} {where:<10} {json.dumps(report[f'{name}_{where}'])}", flush=True)

    run("keyword", lambda t: sum(bool(p.search(t)) for p in PATTERNS) / len(PATTERNS))

    import laya
    agent = laya.load(TUNED)
    def laya_score(text):
        result = agent.predict(text, QUESTION)
        answers = result["answers"] if isinstance(result, dict) else result.answers
        a = answers["has_instruction"]
        return a.get("noul") if isinstance(a, dict) else getattr(a, "noul", None)
    run("laya", laya_score)
    del agent

    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    tok = AutoTokenizer.from_pretrained(PROTECTAI)
    model = AutoModelForSequenceClassification.from_pretrained(PROTECTAI).eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    labels = {v.upper(): k for k, v in model.config.id2label.items()}
    injection_index = labels.get("INJECTION", 1)
    print(f"protectai labels: {model.config.id2label} -> injection index {injection_index}", flush=True)
    @torch.no_grad()
    def protectai_score(text):
        batch = tok(text, truncation=True, max_length=512, return_tensors="pt").to(device)
        return torch.softmax(model(**batch).logits, dim=-1)[0, injection_index].item()
    run("protectai", protectai_score)

    print("=" * 72, flush=True)
    print(json.dumps(report, indent=2), flush=True)
    print("=" * 72, flush=True)


if __name__ == "__main__":
    main()
