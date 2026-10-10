"""Fine-tune Laya on MoneyTrail's injection-screening data.

Motivation (measured, see docs/laya_base_*.json): the base checkpoint ranks injected
documents well inside a split (test AUC 0.982) but its absolute probabilities move with
document phrasing (validation AUC 0.724, clean mean 0.725 vs test clean mean 0.124). A
threshold fitted on validation therefore flags nothing on test. The goal of this run is a
checkpoint whose operating point transfers across unseen phrasing.

Usage: python scripts/laya_finetune.py [--epochs 3] [--device mps|cpu]
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
os.environ.setdefault('USE_TF', '0')
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path('data/laya/train.jsonl'))
    parser.add_argument('--eval-data', type=Path, default=Path('data/laya/validation.jsonl'))
    parser.add_argument('--out', type=Path, default=Path('runtime/laya-moneytrail'))
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--device', default='mps')
    parser.add_argument('--freeze-encoder', action='store_true')
    args = parser.parse_args()

    from huggingface_hub import snapshot_download
    from laya.train import finetune, TrainConfig

    base = snapshot_download('convaiinnovations/laya', allow_patterns=['model.safetensors', 'encoder/*', 'tokenizer/*', 'rl_agent_config.json'])
    config = TrainConfig(epochs=args.epochs, micro_batch=8, grad_accum=4,
                         freeze_encoder=args.freeze_encoder, seed=104,
                         eval_data=str(args.eval_data), log_every=25)
    start = time.time()
    summary = finetune(str(args.data), base, str(args.out), config=config, device=args.device)
    summary['wall_seconds'] = round(time.time() - start, 1)
    summary['device'] = args.device
    Path('docs').mkdir(exist_ok=True)
    Path('docs/laya_finetune_run.json').write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, (list, dict))}, indent=2, default=str))
    print('checkpoint ->', args.out)
