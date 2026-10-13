# MoneyTrail — demo script

Every number below is measured, not estimated. Re-measure before recording if the code changes.

Setup: `python scripts/run.py`, browser at `http://127.0.0.1:5173`, mode **Live AI · Qwen3-30B-A3B**.
Total runtime at this pace: about 2 minutes 30 seconds.

## 0:00 — The question (hold on the landing screen)

> "Ten thousand dollars left. Nine thousand six hundred and fifty arrived. Three companies touched this payment, each one holding its own records, and none of them can read the others'. Everybody's books say they're correct. Three hundred and fifty dollars is still missing."

On screen: the KPI row, and 1,200 real transaction records in the graph behind it. Say that the dense cloud is the sender's own history — the other organizations' records are not there, because they are private.

## 0:20 — Trace (click Investigate payment)

> "I'm not going to tell it where to look. The manager decides who to ask."

Point at the activity feed as it fills. Name what is actually happening: each request is a real A2A JSON-RPC call to a separate service, carrying an HMAC capability token scoped to this case and this payment reference. Nine records arrive from three organizations in under four seconds.

## 0:50 — The twist

> "The processor explains the deduction: a three hundred and fifty dollar fee. So we go and read the agreement it was charged under. The agreement says thirty-five."

Point at the two findings: **Money trail reconciles** (verified) and **Deduction exceeds agreement** (conflicting). Then the recommendation: request a $315.00 adjustment.

Say the important part out loud:

> "The arithmetic was not done by a language model. A calculator did it. The model read the document; the system only accepted that reading because it matched the agreement's attested fields and because the quote it cited appears verbatim in the source."

## 1:30 — The challenge (click Add $350 amendment)

> "Here's the part I can't fake. You change the evidence."

The case re-opens at version 2, re-retrieves, re-verifies.

> "Three hundred and fifteen becomes zero. The recommendation is withdrawn — not edited, withdrawn — and the button changes from 'approve correction' to 'approve closure'. The earlier conclusion is invalidated because the evidence changed."

## 2:00 — Why the architecture, not the model

Hold on the resolution card and give the measured comparison:

> "We ran the same thirty held-out cases through a single model with every record handed to it and nothing to retrieve. It got ten. Eighteen of its answers were resolutions it had no evidence to support. Our verifier gets thirty out of thirty, and agrees with first principles on five thousand random payments."

> "Then we attacked it. Twenty-one different instructions hidden inside the agreement, run through the live system. Four of them fooled the model that reads the document. None of them changed the outcome — a fooled reader escalates to a person, it never produces a decision."

> "The model is not what makes this accurate. The checks are."

## 2:20 — Close

> "Finding the money was the first step. Checking the explanation was the important one."

## Measured facts you can state on camera

| Claim | Value |
|---|---|
| Live investigation, end to end | about 4 s (median 3.8 s, slowest 6.8 s over 200 runs) |
| Cost per live investigation | about $0.0003 |
| Six cases, approvals and amendment twists, live, ten rounds | 110/110 |
| 120 random payments, live, 20 with an injected note | 114 correct, 6 stopped for a human, 0 wrong |
| Bug planted in the verifier, same 120 payments | 80 wrong results, 80 stopped, 0 got through |
| Deterministic verifier, 30 held-out cases | 30/30, 0 unsupported resolutions |
| Single centralized model, same 30 cases | 10/30, 18 unsupported resolutions |
| Deterministic verifier, 5,000 random payments | 5,000/5,000 against a first-principles oracle |
| 21 distinct injected documents, live | 0 wrong dispositions; 4 escalated to a human |
| Retrieval completeness | 1.0 |
| Graph | 1,271 nodes, 61 FPS median |

## Do not say

- That any bank uses this, or that real counterparties respond this way.
- That the 30 cases are external validation. They are generated fixtures.
- That MoneyTrail beats Swift's 200-hour figure. That is Swift's industry study, measured differently.
- That the injection shows the single model being steered: it also closes the clean case, so that would be unfounded.
- That any of this ran on a real company's records. It has not.
