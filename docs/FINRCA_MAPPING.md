# FinRCA-Bench and MoneyTrail: what maps, what does not

FinRCA-Bench (arXiv 2608.18534, MIT, Pratik Ghawate) is the closest published benchmark to
this work. This document records how the two relate, what we measured, and what integrating
it further would take. Everything marked *measured* comes from `scripts/finrca_eval.py`;
everything marked *analysis* is a reading of the two data models and is not a result.

## How many parties, and why that is the whole difference

*Measured, from FinRCA's own manifest across all 2,250 cases:*

| System named in FinRCA | Cases | Inside one company? |
|---|---|---|
| ERP-AP | 2,250 | yes |
| Bank | 1,357 | **no** |
| ERP-GL | 1,265 | yes |
| ERP-Procurement | 407 | yes |
| PaymentProcessor | 300 | **no** |
| VendorManagement | 246 | yes |
| ERP-Workflow | 147 | yes |
| ReconciliationPlatform | 100 | yes |

FinRCA spans eight systems, but six of them belong to a single enterprise. It is an
**intra-company** reconciliation problem: one owner, one access domain, and an analyst who
is entitled to read all fourteen tables. That is why the benchmark can offer an oracle
retrieval condition at all — handing over every table breaks no boundary.

MoneyTrail spans **three independent companies** — sender, processor, recipient — each
running its own service over its own database, each unable to read the others. The evidence
cannot be handed over; it has to be requested and granted, under a capability token scoped
to one case and one payment reference. No amount of retrieval engineering removes that
boundary, because the boundary is the problem.

This is the gap no public dataset covers. Public reconciliation datasets are flat tables
because they assume one owner.

## What the verifier scored on it

*Measured, all 2,250 cases, FinRCA's oracle-retrieval condition:*

- Recall 1.0, false positive rate 1.0, `discriminates: false`. It flagged every case.
- **0 of 2,250 received a `close` or a `request_correction`.** Every one returned
  `request_evidence`: incomplete trail (1,739), currency conflict (411), no evidence (100).
- 4,263 of 13,108 records mapped to a MoneyTrail evidence kind; 8,845 (67%) had no analogue.

Read it honestly: on accounts-payable data it was never built for, the verifier has no
diagnostic signal. What it does not do is guess. It fails closed, which is the behaviour the
centralized single-model baseline did not have — that one closed cases with missing evidence.

## 16 causes against 3 dispositions

*Analysis, not measured.* MoneyTrail's three outputs are not a smaller version of FinRCA's
sixteen labels. They answer a different question: FinRCA asks *what went wrong*, MoneyTrail
asks *what should a human do now*. The mapping is many-to-one.

| FinRCA class | MoneyTrail disposition | Does our evidence model reach it? |
|---|---|---|
| NO_FAILURE | `close` | yes |
| F02_PO_INVOICE_AMOUNT_MISMATCH | `request_correction` | **yes — this is our exact pattern**: a charge exceeding its authority |
| F14_BANK_ERP_AMOUNT_MISMATCH | `request_correction` | yes — the trail does not balance |
| F06_INVOICE_PAID_TWICE | `request_correction` | yes — duplicate disbursement is an unsupported amount |
| F07_PARTIAL_PAYMENT_RESIDUAL_BALANCE | `request_correction` | yes — settlement does not equal credit |
| F12_ERP_PAYMENT_MISSING_FROM_BANK | `request_evidence` | yes — a required record is absent |
| F13_BANK_TRANSACTION_MISSING_FROM_ERP | `request_evidence` | yes — a required record is absent |
| F01_DUPLICATE_INVOICE | `request_evidence` | yes — duplicate source IDs |
| F04_INCORRECT_VENDOR_ASSOCIATION | `request_evidence` | yes — record kind and organization disagree |
| F05_PAYMENT_WITHOUT_VALID_INVOICE | `request_evidence` | yes — supporting record missing |
| F15_INCORRECT_PAYMENT_BANK_MATCH | `request_evidence` | yes — ambiguous payment reference |
| F10_WRONG_ACCOUNTING_PERIOD | `request_evidence` | partly — our effective-date check is analogous, but we model no accounting period |
| F03_QUANTITY_MISMATCH | — | **no** — we model no quantities or line items |
| F08_APPROVAL_WORKFLOW_FAILURE | — | **no** — we model no approval chain |
| F09_GL_POSTING_MISMATCH | — | **no** — we model no general ledger |
| F11_VENDOR_MASTER_CHANGE_CONFLICT | — | **no** — we model no vendor master history |

Eleven of sixteen reach a disposition; four need a data model we do not have; one is partial.

The conclusion is that the number of output classes is not the limiting factor. **The
evidence model is.** Adding thirteen more output labels to the verifier would change nothing
until there are quantities, approval chains, GL lines and vendor history for it to check —
and each of those is a new deterministic check, not a new label.

FinRCA's own paper reaches a compatible conclusion: a correct root-cause label is a weak
proxy for an auditable diagnosis, and retrieval design mattered more than the reasoning model.

## What integrating it further would take

1. **Extend the evidence model before the label set.** Add `po_line`, `approval`, `gl_line`
   and `vendor_change` kinds with their own deterministic checks. Each one unlocks its FinRCA
   classes and, more importantly, each is checkable rather than guessed.
2. **Keep three dispositions, name the cause.** The verifier already produces a cause string
   in every finding title — "Deduction exceeds agreement", "Payment trail does not balance",
   "Duplicate evidence", "Ambiguous payment reference", "Untrusted provenance". Surfacing
   those as a labelled cause is presentation, not architecture.
3. **Only then score the 16-class task**, and report it beside the disposition accuracy
   rather than instead of it.

Nothing here is required for the current submission. The measured generalization probe is.

Reproduce with:

```bash
git clone https://github.com/PratikGhawate/FinRCA-AI-Bench /tmp/finrca
python scripts/finrca_eval.py /tmp/finrca --output docs/finrca_eval.json
```
