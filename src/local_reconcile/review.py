from dataclasses import replace
from .domain import ConfirmedPair, ReviewEvent, ReviewState, LocalReconcileError
from .matching import stable_id

def _transactions(snapshot):
    return ({t.id:t for t in snapshot.bank.transactions},
            {t.id:t for t in snapshot.ledger.transactions})

def apply_review(snapshot,event):
    if event.sequence != len(snapshot.review.events)+1 or type(event.sequence) is not int:
        raise LocalReconcileError("sequence","操作序号不连续")
    bank,ledger = _transactions(snapshot)
    if event.bank_id not in bank or event.ledger_id not in ledger:
        raise LocalReconcileError("row_reference","所选记录不属于当前核对")
    key = (event.bank_id,event.ledger_id)
    pairs = list(snapshot.review.pairs)
    rejected = set(snapshot.review.rejected)
    existing = next((p for p in pairs if (p.bank_id,p.ledger_id)==key),None)
    if event.kind == "confirm":
        b,l = bank[event.bank_id],ledger[event.ledger_id]
        if b.amount_minor != l.amount_minor:
            raise LocalReconcileError("amount_difference","金额或方向不一致，只能记录差异，不能确认为相符")
        if any(p.bank_id==event.bank_id or p.ledger_id==event.ledger_id for p in pairs):
            raise LocalReconcileError("occupied","这笔记录已参与其他已确认关系，请先撤销")
        candidate = next((c for c in snapshot.result.candidates if (c.bank_id,c.ledger_id)==key),None)
        if (candidate is None or candidate.conflicts) and not event.note.strip():
            raise LocalReconcileError("manual_reason","手工指定或冲突关系需要填写确认依据")
        basis = event.note.strip() or candidate.rule
        pairs.append(ConfirmedPair(stable_id("confirmed",*key),*key,basis))
        rejected.discard(key)
    elif event.kind == "reject":
        if existing:
            raise LocalReconcileError("confirmed","请先撤销已确认关系")
        rejected.add(key)
    elif event.kind == "undo":
        if existing:
            pairs.remove(existing)
        elif key in rejected:
            rejected.remove(key)
        else:
            raise LocalReconcileError("undo","所选关系没有可撤销的操作")
    else:
        raise LocalReconcileError("event","操作类型不支持")
    state = ReviewState(tuple(pairs),tuple(sorted(rejected)),snapshot.review.events+(event,))
    return replace(snapshot,review=state)

def classify_rows(snapshot):
    bank,ledger = _transactions(snapshot)
    confirmed = {rid for p in snapshot.review.pairs for rid in (p.bank_id,p.ledger_id)}
    pending = set()
    rejected = set(snapshot.review.rejected)
    for c in snapshot.result.candidates:
        if (c.bank_id,c.ledger_id) not in rejected and c.bank_id not in confirmed and c.ledger_id not in confirmed:
            pending.update((c.bank_id,c.ledger_id))
    for g in snapshot.result.groups:
        if g.truncated:
            bs=set(g.bank_ids)-confirmed;ls=set(g.ledger_ids)-confirmed
            if bs and ls:
                pending.update(bs|ls)
    return {rid:("confirmed" if rid in confirmed else "pending" if rid in pending else "unmatched") for rid in chain_ids(bank,ledger)}

def chain_ids(bank,ledger):
    return tuple(bank)+tuple(ledger)

def confirm_batch(snapshot,candidate_ids):
    if len(set(candidate_ids)) != len(candidate_ids):
        raise LocalReconcileError("batch","批量选择包含重复候选")
    by_id = {c.id:c for c in snapshot.result.candidates}
    group_rows = {rid for g in snapshot.result.groups for rid in g.bank_ids+g.ledger_ids}
    selected=[]
    for cid in candidate_ids:
        c = by_id.get(cid)
        if c is None or c.rule!="reference" or c.conflicts or c.bank_id in group_rows or c.ledger_id in group_rows:
            raise LocalReconcileError("batch","批量确认只接受无歧义、无冲突的强依据候选")
        selected.append(c)
    updated=snapshot
    for c in selected:
        updated=apply_review(updated,ReviewEvent(len(updated.review.events)+1,"confirm",c.bank_id,c.ledger_id))
    return updated
