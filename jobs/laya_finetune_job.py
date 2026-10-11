# /// script
# requires-python = ">=3.10"
# dependencies = ["laya==0.4.2", "huggingface_hub>=0.34.0"]
# ///
"""Fine-tune Laya for MoneyTrail injection screening on a Hugging Face GPU.

One job runs the whole experiment: build the data, measure the base checkpoint, fine-tune,
measure again, and fit a threshold on validation to see whether it transfers to test. The
base checkpoint's defect is transfer, not ranking -- it scores test AUC 0.98 and validation
AUC 0.72 with clean means of 0.12 and 0.73, so a validation threshold flags nothing on test.

Run: hf jobs uv run --flavor a10g-small --secrets HF_TOKEN jobs/laya_finetune_job.py
"""
import json, os, sys, time, urllib.request
from pathlib import Path

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

BASE = "convaiinnovations/laya"
DATASET_SRC = "https://raw.githubusercontent.com/chetan-codes/moneytrail/main/scripts/laya_dataset.py"
REPO = os.environ.get("PUSH_REPO", "")
DATA = Path("data")


def build_data():
    """Single source of truth: the generator that lives in the repo, not a copy."""
    source = urllib.request.urlopen(DATASET_SRC, timeout=60).read().decode()
    namespace = {"__name__": "laya_dataset"}
    exec(compile(source, "laya_dataset.py", "exec"), namespace)
    DATA.mkdir(exist_ok=True)
    for index, split in enumerate(("train", "validation", "test")):
        rows = namespace["rows"](split, 104 + index)
        with (DATA / f"{split}.jsonl").open("w") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        print(f"  {split}: {len(rows)} rows", flush=True)


def metrics(agent, path):
    rows = [json.loads(l) for l in Path(path).open()]
    scored = []
    for row in rows:
        result = agent.predict(row["state"], row["questions"])
        answers = result["answers"] if isinstance(result, dict) else result.answers
        a = answers["has_instruction"]
        p = a.get("noul") if isinstance(a, dict) else getattr(a, "noul", None)
        if isinstance(p, (int, float)):
            scored.append((bool(row["expected"]["has_instruction"]), float(p)))
    injected = [p for t, p in scored if t]
    clean = [p for t, p in scored if not t]
    pairs = [(a, b) for a in injected for b in clean]
    auc = sum((a > b) + 0.5 * (a == b) for a, b in pairs) / len(pairs) if pairs else None
    return dict(n=len(scored), auc=round(auc, 4) if auc else None,
                accuracy_at_half=round(sum((p >= .5) == t for t, p in scored) / len(scored), 4),
                clean_mean=round(sum(clean) / len(clean), 4),
                injected_mean=round(sum(injected) / len(injected), 4)), scored


def transfer(val_scores, test_scores):
    """Pick the threshold on validation only, then report what it does on test."""
    def accuracy(scores, t):
        return sum((p >= t) == y for y, p in scores) / len(scores)
    best = max(sorted({round(p, 4) for _, p in val_scores}), key=lambda t: accuracy(val_scores, t))
    tp = sum(p >= best and y for y, p in test_scores)
    fn = sum(p < best and y for y, p in test_scores)
    fp = sum(p >= best and not y for y, p in test_scores)
    return dict(threshold_fitted_on_validation=best,
                validation_accuracy=round(accuracy(val_scores, best), 4),
                test_accuracy=round(accuracy(test_scores, best), 4),
                test_true_positives=tp, test_false_negatives=fn, test_false_positives=fp)


def main():
    import torch, laya
    from huggingface_hub import snapshot_download
    from laya.train import finetune, TrainConfig

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device} torch={torch.__version__} "
          f"gpu={torch.cuda.get_device_name(0) if device == 'cuda' else 'none'}", flush=True)

    print("building data", flush=True)
    build_data()

    base_dir = snapshot_download(BASE, allow_patterns=["model.safetensors", "encoder/*", "tokenizer/*", "rl_agent_config.json"])
    report = {"device": device, "base_model": BASE}

    print("scoring base checkpoint", flush=True)
    agent = laya.load(BASE)
    report["base_validation"], base_val = metrics(agent, DATA / "validation.jsonl")
    report["base_test"], base_test = metrics(agent, DATA / "test.jsonl")
    report["base_transfer"] = transfer(base_val, base_test)
    print(json.dumps(report["base_transfer"], indent=2), flush=True)
    del agent

    print("fine-tuning", flush=True)
    start = time.time()
    config = TrainConfig(epochs=3, micro_batch=16, grad_accum=2, seed=104,
                         eval_data=str(DATA / "validation.jsonl"), log_every=5)
    summary = finetune(str(DATA / "train.jsonl"), base_dir, "out", config=config, device=device)
    report["train_seconds"] = round(time.time() - start, 1)
    report["train_summary"] = {k: v for k, v in summary.items() if isinstance(v, (int, float, str))}

    print("scoring fine-tuned checkpoint", flush=True)
    tuned = laya.load("out")
    report["tuned_validation"], tuned_val = metrics(tuned, DATA / "validation.jsonl")
    report["tuned_test"], tuned_test = metrics(tuned, DATA / "test.jsonl")
    report["tuned_transfer"] = transfer(tuned_val, tuned_test)

    print("=" * 72, flush=True)
    print(json.dumps(report, indent=2), flush=True)
    print("=" * 72, flush=True)

    if REPO:
        from huggingface_hub import HfApi
        api = HfApi()
        api.create_repo(REPO, repo_type="model", private=True, exist_ok=True)
        Path("out/moneytrail_eval.json").write_text(json.dumps(report, indent=2))
        api.upload_folder(folder_path="out", repo_id=REPO, repo_type="model")
        print(f"pushed checkpoint -> {REPO} (private)", flush=True)


if __name__ == "__main__":
    main()
