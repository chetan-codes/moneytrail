"""Fail-closed deterministic payment verification over returned evidence only.

Structured agreement metadata represents synthetic system attestations, not a claim
that arbitrary contracts can be reliably interpreted without a model or human.
"""
from __future__ import annotations
import re
from datetime import date, datetime

ROLES = {'debit':'sender','instruction':'sender','invoice':'sender',
         'incoming':'processor','fee':'processor','settlement':'processor',
         'agreement':'processor','amendment':'processor','credit':'recipient','allocation':'recipient'}
REQUIRED = ('debit','incoming','fee','settlement','credit')


def cite(record, amount_minor):
    """The sentence in the source stating this figure, so an approver can check the claim against the record."""
    content=record.get('content')
    if not isinstance(content,str):
        return None
    needle=f'USD {amount_minor/100:,.2f}'
    for sentence in re.split(r'(?<=[.;:])\s+',content):
        if needle in sentence:
            return dict(evidence_id=record['id'],quote=sentence.strip(),value=needle)
    return None


def verify(records: list[dict]) -> dict:
    findings=[]
    def finding(status,title,detail,items,citations=()):
        ids=list(dict.fromkeys(r['id'] for r in items if isinstance(r,dict) and isinstance(r.get('id'),str)))
        # Only spans located verbatim in a source are cited; an absent figure yields no highlight rather than a guess.
        found=[c for c in citations if c]
        findings.append(dict(id=f'finding:{len(findings)+1}',status=status,title=title,detail=detail,evidence_ids=ids,citations=found))
    def unresolved(title,detail,items=()):
        finding('unresolved',title,detail,items)
        return dict(findings=findings,unsupported_minor=None,recommendation=dict(
            action='request_evidence',amount_minor=0,summary=detail,
            evidence_ids=list(dict.fromkeys(i for f in findings for i in f['evidence_ids']))))
    if not records:
        return unresolved('No evidence','No records were returned. Request payment records.')
    if any(not isinstance(r,dict) or not isinstance(r.get('id'),str) or not r['id'] for r in records):
        return unresolved('Invalid evidence','Every evidence record must have a nonempty source ID.')
    if any(not isinstance(r.get('kind'),str) or not isinstance(r.get('organization'),str)
           or not isinstance(r.get('reference'),str) or not r['reference']
           or not isinstance(r.get('metadata',{}),dict) for r in records):
        return unresolved('Invalid evidence fields','Evidence requires string kind, organization, reference and object metadata.',records)
    if len({r['id'] for r in records})!=len(records):
        return unresolved('Duplicate evidence','Duplicate source IDs must be resolved before verification.',records)
    if any(r.get('kind') not in ROLES or r.get('organization')!=ROLES[r['kind']] for r in records):
        return unresolved('Untrusted provenance','Record kind and organization do not match permitted sources.',records)
    references={r.get('reference') for r in records}
    if len(references)!=1 or not next(iter(references)):
        return unresolved('Ambiguous payment reference','Returned records do not identify one consistent payment reference.',records)
    if any(r.get('currency')!='USD' for r in records):
        return unresolved('Currency conflict','This prototype verifies USD only; mixed or unsupported currencies require review.',records)
    by_kind={k:[r for r in records if r['kind']==k] for k in ROLES}
    if any(len(by_kind[k])!=1 for k in REQUIRED):
        return unresolved('Incomplete or ambiguous payment trail','Exactly one debit, incoming record, fee, settlement, and recipient credit are required.',records)
    for kind,items in by_kind.items():
        if kind not in ('agreement','amendment') and len(items)>1:
            return unresolved('Ambiguous source records',f'Multiple {kind} records require manual matching.',items)
    financial=[r for r in records if r['kind'] not in ('agreement','amendment')]
    if any(type(r.get('amount_minor')) is not int or r['amount_minor']<0 for r in financial):
        return unresolved('Invalid monetary value','Amounts must be nonnegative integer minor units.',financial)
    try:
        dates={r['id']:datetime.fromisoformat(r['timestamp'].replace('Z','+00:00')).date() for r in records}
        payment_date=dates[by_kind['debit'][0]['id']]
    except (KeyError,TypeError,ValueError,AttributeError):
        return unresolved('Invalid dates','Every source record must contain a valid timestamp.',records)
    debit,incoming,fee,settlement,credit=(by_kind[k][0] for k in REQUIRED)
    amount=lambda r:r['amount_minor']
    if amount(debit)!=amount(incoming) or amount(incoming)!=amount(fee)+amount(settlement) or amount(settlement)!=amount(credit):
        finding('conflicting','Payment trail does not balance','Debit, processor receipt, deduction, settlement, and credit do not reconcile.',[debit,incoming,fee,settlement,credit])
        return unresolved('Unresolved arithmetic','Request missing or corrected ledger records before recommending an adjustment.',[debit,incoming,fee,settlement,credit])
    for kind,expected in [('instruction',amount(debit)),('invoice',amount(debit)),('allocation',amount(credit))]:
        if by_kind[kind] and amount(by_kind[kind][0])!=expected:
            return unresolved('Supporting record conflict',f'The {kind} amount conflicts with the observed payment trail.',by_kind[kind])
    finding('verified','Money trail reconciles',f'{amount(debit)/100:,.2f} USD sent = {amount(credit)/100:,.2f} received + {amount(fee)/100:,.2f} deducted.',[debit,incoming,fee,settlement,credit],
        [cite(debit,amount(debit)),cite(fee,amount(fee)),cite(credit,amount(credit))])
    agreements=by_kind['agreement']
    if len(agreements)!=1:
        return unresolved('Agreement missing or ambiguous','Cannot verify the deduction without exactly one authoritative base agreement.',agreements)
    documents=agreements+by_kind['amendment']
    for document in documents:
        meta=document.get('metadata') or {}
        if meta.get('authorized') is not True or meta.get('issuer')!='processor' or type(meta.get('fee_minor')) is not int or meta['fee_minor']<0:
            return unresolved('Agreement authority unresolved','Document lacks valid authoritative synthetic fee metadata; human review is required.',[document])
        try:
            effective=date.fromisoformat(meta['effective_date'])
        except (KeyError,ValueError,TypeError):
            return unresolved('Agreement date unresolved','A document has no valid effective date.',[document])
        if effective>payment_date:
            return unresolved('Document not applicable','A supplied agreement or amendment takes effect after this payment; review applicability.',[document])
    chosen=agreements[0]
    amendments=by_kind['amendment']
    if len(amendments)>1:
        return unresolved('Conflicting amendments','Multiple amendments require an explicit verified precedence chain.',amendments)
    if amendments:
        amendment=amendments[0]
        meta=amendment['metadata']
        if meta.get('supersedes')!=chosen['id'] or meta['effective_date']<chosen['metadata']['effective_date']:
            return unresolved('Amendment precedence unresolved','The amendment does not establish valid precedence over the supplied agreement.',documents)
        chosen=amendment
    allowed=chosen['metadata']['fee_minor']
    observed=amount(fee)
    ids=[r['id'] for r in [debit,incoming,fee,settlement,credit]+documents]
    if allowed==observed:
        finding('verified','Deduction supported','The observed deduction matches the applicable structured agreement fee.',[fee,chosen],
            [cite(fee,observed),cite(chosen,allowed)])
        recommendation=dict(action='close',amount_minor=0,summary='The payment trail balances and the supplied agreement supports the deduction.',evidence_ids=ids)
        unsupported=0
    elif observed>allowed:
        unsupported=observed-allowed
        finding('conflicting','Deduction exceeds agreement',f'Observed {observed/100:,.2f} USD; permitted {allowed/100:,.2f} USD; unsupported difference {unsupported/100:,.2f} USD.',[fee,chosen],
            [cite(fee,observed),cite(chosen,allowed)])
        recommendation=dict(action='request_correction',amount_minor=unsupported,summary=f'Request a {unsupported/100:,.2f} USD adjustment, subject to human review of the supplied evidence.',evidence_ids=ids)
    else:
        return unresolved('Deduction below agreement','The deduction is lower than the agreement fee. Request an explanation rather than infer an adjustment.',[fee,chosen])
    return dict(findings=findings,recommendation=recommendation,unsupported_minor=unsupported)
