"""Refund and advance accounting; all money is integer minor units."""
from .workspace import fail, _integer, _note

KINDS = ("退款", "冲销", "退票")

def allocation_net(s, key):
    return s.allocations[key]["amount_minor"] - sum(p["amount_minor"] for p in s.refunds.values() if p.get("allocation")==key)

def advance_refunded(s, key):
    return sum(p["amount_minor"] for p in s.refunds.values() if p.get("advance")==key)

def advance_remaining(s, key):
    return s.advances[key]["amount_minor"] - advance_refunded(s,key) - sum(allocation_net(s,k) for k,p in s.allocations.items() if p.get("advance")==key)

def cash_free(w,s,rid):
    if any(rid in (p["outgoing"],p["incoming"]) for p in s.transfers.values()):return 0
    used=sum(allocation_net(s,k) for k,p in s.allocations.items() if p["cash"]==rid and not p.get("advance"))
    used+=sum(p["amount_minor"]-advance_refunded(s,k) for k,p in s.advances.items() if p["cash"]==rid)
    used+=sum(p["amount_minor"] for p in s.refunds.values() if p["original"]==rid or p["cash"]==rid)
    return abs(w.records[rid].amount_minor)-used

def item_cash_used(s,rid):
    return sum(allocation_net(s,k) for k,p in s.allocations.items() if p["item"]==rid)

def item_credit_used(s,rid):
    return sum(p["amount_minor"] for p in s.credits.values() if p["item"]==rid)

def item_used(s,rid):
    return item_cash_used(s,rid)+item_credit_used(s,rid)

def advance_rows(w):
    s=w.state
    return [{"id":k,**p,"remaining_minor":advance_remaining(s,k)} for k,p in s.advances.items()]

def occupied_settlements(s):
    return {p["cash"] for p in s.advances.values()}|{x for p in s.refunds.values() for x in (p["original"],p["cash"])}

def validate_balances(w,s):
    # Rechecked after every event, including undo, so later reuse cannot break invariants.
    touched={p["cash"] for p in s.allocations.values()}|occupied_settlements(s)
    if any(cash_free(w,s,rid)<0 for rid in touched):fail("操作导致收付款可用余额不足，请先撤销后续处理")
    if any(advance_remaining(s,k)<0 for k in s.advances):fail("操作导致预收预付款余额不足")
    for rid in {p["item"] for p in s.allocations.values()}|{p["item"] for p in s.credits.values()}:
        amount=item_used(s,rid)
        if not 0<=amount<=w.records[rid].amount_minor:fail("操作导致单据超额核销，请先撤销后续核销")

def apply_settlement(w,s,e,active):
    d=e.data
    if e.kind=="register_advance":
        cash=active.get(d.get("cash"));amount=_integer(d.get("amount_minor"),True);evidence=_note(d,"evidence",True)
        if not cash or cash.role!="bank" or not cash.amount_minor or not cash.party:fail("预收预付须选择有明确往来单位的银行收付款")
        if amount>cash_free(w,s,cash.id):fail("登记金额超过银行收付款可用余额")
        s.advances[f"advance-{e.seq}"]={"cash":cash.id,"amount_minor":amount,"party":cash.party,"kind":"预收款" if cash.amount_minor>0 else "预付款","evidence":evidence,"period":s.period}
    elif e.kind=="allocate_advance":
        key=d.get("advance");a=s.advances.get(key);item=active.get(d.get("item"));amount=_integer(d.get("amount_minor"),True);note=_note(d)
        if not a or not item or item.role not in ("receivable","payable"):fail("请选择预收预付款和应收应付单据")
        cash=w.records[a["cash"]]
        if cash.id not in active or item.party!=a["party"] or (cash.amount_minor>0)!=(item.role=="receivable"):fail("预收预付只能核销同一单位、对应收付方向的单据")
        if item.day<cash.day:fail("预收预付核销单据日期不能早于原收付款")
        if amount>advance_remaining(s,key) or amount>item.amount_minor-item_used(s,item.id):fail("核销金额超过预收预付余额或单据余额")
        s.allocations[f"allocation-{e.seq}"]={"cash":cash.id,"item":item.id,"amount_minor":amount,"note":note,"period":s.period,"advance":key}
    elif e.kind=="refund":
        original,cash=active.get(d.get("original")),active.get(d.get("cash"));amount=_integer(d.get("amount_minor"),True)
        category=d.get("category");evidence=_note(d,"evidence",True)
        if category not in KINDS:fail("退款冲销类别无效")
        if not original or not cash or original.role!="bank" or cash.role!="bank" or original.amount_minor*cash.amount_minor>=0:fail("须选择原银行收付款及反方向的退款、冲销或退票流水")
        if cash.day<original.day:fail("退款流水日期不能早于原收付款")
        if any(original.id==p["cash"] or cash.id==p["original"] for p in s.refunds.values()):fail("退款流水不能再作为原收付款串联退款")
        if any(original.id in (p["outgoing"],p["incoming"]) or cash.id in (p["outgoing"],p["incoming"]) for p in s.transfers.values()):fail("内部转账不能登记为客户供应商退款")
        if amount>cash_free(w,s,cash.id):fail("退款流水可用余额不足")
        allocation=d.get("allocation");advance=d.get("advance")
        if allocation and advance:fail("请选择原核销或未核销的预收预付款其中一项")
        if allocation:
            p=s.allocations.get(allocation)
            if not p or p["cash"]!=original.id or amount>allocation_net(s,allocation):fail("退款超过原核销金额或原核销不属于所选流水")
            advance=p.get("advance","")
        elif advance:
            a=s.advances.get(advance)
            if not a or a["cash"]!=original.id or amount>advance_remaining(s,advance):fail("退款超过预收预付可退余额")
        elif amount>cash_free(w,s,original.id):fail("原款项已分配，请指定对应核销或预收预付款")
        s.refunds[f"refund-{e.seq}"]={"original":original.id,"cash":cash.id,"amount_minor":amount,"category":category,"evidence":evidence,"allocation":allocation or "","advance":advance or "","period":s.period}
    else:
        target=d.get("target");_note(d,"note",True)
        if e.kind=="undo_refund":group=s.refunds
        else:
            group=s.advances
            if any(p.get("advance")==target for p in s.allocations.values()) or any(p.get("advance")==target for p in s.refunds.values()):fail("请先撤销该预收预付款的核销和退款")
        if target not in group:fail("操作不存在或已撤销")
        del group[target]
