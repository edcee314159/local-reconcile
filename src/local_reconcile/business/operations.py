from .workspace import active_records, _used, period_end
from ..domain import check_cancel, never_cancel
from .settlements import item_used, item_cash_used, item_credit_used, cash_free, occupied_settlements

def outstanding(w):
    s=w.state;matched=_used(s.matches);end=period_end(s.period)
    return [{"record":r,"age_days":(end-r.day).days,"explained":any(r.id in (p["bank"],p["ledger"]) for p in s.explanations.values())}
            for r in active_records(w).values() if r.role in ("bank","ledger") and r.id not in matched]

def open_items(w):
    end=period_end(w.state.period)
    return [{"record":r,"allocated_minor":item_cash_used(w.state,r.id),"credited_minor":item_credit_used(w.state,r.id),
             "remaining_minor":r.amount_minor-item_used(w.state,r.id),
             "age_days":(end-r.day).days,"overdue_days":max(0,(end-r.due).days) if r.due else None}
            for r in active_records(w).values() if r.role in ("receivable","payable")]

def cash_remaining(w,rid):
    return cash_free(w,w.state,rid)

def suggest_allocations(w,cancelled=never_cancel):
    from collections import defaultdict
    by_party=defaultdict(list);result=[]
    for item in open_items(w):
        r=item["record"]
        if item["remaining_minor"]>0:by_party[r.party,r.role].append(item)
    for cash in active_records(w).values():
        check_cancel(cancelled)
        if cash.role!="bank" or not cash.amount_minor or not cash.party:continue
        remaining=cash_remaining(w,cash.id)
        if not remaining:continue
        possible=by_party.get((cash.party,"receivable" if cash.amount_minor>0 else "payable"),())
        # Ambiguous candidate sets are not expanded indefinitely or auto-allocated.
        if len(possible)>100:continue
        for item in possible:
            r=item["record"]
            if cash.reference and r.reference and cash.reference!=r.reference:continue
            result.append((cash.id,r.id,min(remaining,item["remaining_minor"])))
    return tuple(result)

def suggest_transfers(w,cancelled=never_cancel):
    from collections import defaultdict
    incoming=defaultdict(list);result=[]
    records=active_records(w);occupied={x for p in w.state.transfers.values() for x in (p["outgoing"],p["incoming"])}
    allocated={p["cash"] for p in w.state.allocations.values()}|occupied_settlements(w.state)
    for r in records.values():
        if r.role=="bank" and r.amount_minor>0 and r.id not in occupied|allocated:incoming[r.amount_minor].append(r)
    for out in records.values():
        check_cancel(cancelled)
        if out.role!="bank" or out.amount_minor>=0 or out.id in occupied|allocated:continue
        pool=incoming.get(-out.amount_minor,())
        if len(pool)>100:continue
        for inc in pool:
            if out.account==inc.account or abs((out.day-inc.day).days)>w.settings.window_days:continue
            if out.reference and inc.reference and out.reference!=inc.reference:continue
            if not (out.reference and out.reference==inc.reference) and not (out.party and out.party==inc.party):continue
            result.append((out.id,inc.id))
    return tuple(result)
