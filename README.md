# MoneyTrail

**Three companies. Three versions of the truth. One investigation you can verify.**

$10,000 sent. $9,650 received. Three organizations, each holding its own records, none able to read the others'. MoneyTrail locates the deduction, checks it against the governing agreement, and proposes a disposition a human approves.

Finding the money is the first step. Checking the explanation is the important one.

## What is real and what is synthetic

| Real | Synthetic |
|---|---|
| Agent-to-agent exchange over the official A2A Python SDK (0.3.22) | All organizations, payments, documents and amendments |
| Three isolated services, each reading only its own SQLite store | The `PAY-104` reference and the $35 → $350 fee error |
| HMAC capability tokens scoped per case and reference | |
| Deterministic verification arithmetic | |
| Live open-model inference (`Qwen/Qwen3-8B`) when selected | |
| Human approval, idempotency and version checks | |

No money moves. "Approved request", "accepted" and "adjustment posted" are separate states.

## The three cases

1. **Valid deduction** — the agreement permits $350. Recommend closing.
2. **Incorrect deduction** — the agreement permits $35. Recommend requesting a $315 adjustment.
3. **Insufficient evidence** — no agreement available. Request evidence; leave unresolved.

Anyone can add a seeded, clearly labelled amendment permitting the higher fee. The case re-opens at a new version, re-verifies, and the recommendation is withdrawn — the earlier conclusion is invalidated, not quietly edited.

## Modes

- `deterministic` — real A2A retrieval and real arithmetic, explicitly **no** model inference.
- `live` — the same retrieval, with `Qwen/Qwen3-8B` acting as manager, document verifier and resolution reviewer.
- `replay` — explicitly labelled playback of recorded events. Never calls a model, actions disabled.

A failed model call never falls back to deterministic output and pretends inference happened.

## Verification is not "a second model agreeing"

Amounts, currencies, references, duplicates and citation validity are checked by deterministic code. The model's document reading is accepted only when it matches the document's attested fields *and* its supporting quote appears verbatim in the source. The resolution reviewer cannot change a disposition the verifier did not reach.

## Run it

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
python scripts/run.py
```

Dashboard on `http://127.0.0.1:5173`, API docs on `http://127.0.0.1:8000/docs`. Local processes share your OS user; use `compose.yaml` for filesystem mount isolation.

Live inference is off until you set `HF_TOKEN` and the actual provider token rates in `.env` (copy `.env.example`). It refuses to make a paid call until those rates are present, and reserves estimated spend against `HF_DEV_BUDGET_USD` before dispatch.

## Evaluation

```bash
python scripts/evaluate.py --output docs/evaluation.json
```

30 held-out synthetic cases across valid fees, incorrect fees, valid amendments, missing evidence, reference ambiguity and malicious document instructions. These are generated fixtures, not independent external validation. See `docs/DATASET_CARD.md`.

## Context

Payment investigations are a documented operational problem — Swift's April 2025 report estimates roughly 1–3% of payments raise enquiries, with five to ten manual touchpoints per case. Those are Swift's own industry figures supporting Swift's product, and we do not claim to beat them with a local demo. Banks already move investigation messages; MoneyTrail is about turning the records behind those messages into a resolution a human can verify.

## Layout

- `backend/` — coordinator (`app.py`), org service (`org_service.py`), verifier (`verify.py`), generator (`data.py`), model client (`model.py`), capability tokens (`security.py`)
- `frontend/` — React + TypeScript investigation console
- `scripts/` — `run.py` (demo), `evaluate.py` (pilot), `compose_setup.py` (secrets)
- `docs/CONTRACT.md` — the frozen shared contract

## Demo

[**Watch the narrated walkthrough (93s)**](docs/demo.mp4) · silent loop below

![MoneyTrail investigation](docs/demo.gif)

A recorded walkthrough of the real application: trace the payment, find the $315 the agreement does not support, then add a valid amendment and watch the recommendation be withdrawn. `docs/DEMO_SCRIPT.md` has the narration and the measured numbers behind every claim.

## Measured results

| | Deterministic verifier | One centralized model, same evidence |
|---|---|---|
| 30 held-out cases | **30/30** | 6/30 |
| Unsupported resolutions | **0** | 19 |
| Documents containing an injected instruction | **5/5 correct** | 0/5 — closes all five |
| Live end-to-end investigation | 2.4–4.2 s, ~$0.0002 | — |

The injection comparison is a matched pair: the same five cases, with and without one added paragraph. Without it the centralized model correctly asks for a correction five times out of five; with it, it closes all five. The deterministic verifier is unaffected either way.
