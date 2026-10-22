"""Explain net settlements using explicit component and order evidence."""
from collections import defaultdict
from copy import deepcopy
import json
from .workspace import active_records, fail, _note, _ids
from ..matching import stable_id


def _order_fingerprint(checks):
    return stable_id("net-order-proof",json.dumps(checks,ensure_ascii=False,sort_keys=True,separators=(",",":")))

def group_id(party, settlement):
    return stable_id("net-settlement",party,settlement)


def touch_net(w,s,e):
    """Source revisions do not revive old confirmations after exclude/restore."""
    if e.kind=="import_batch":
        batch=next((b for b in w.batches if b.id==e.data.get("batch")),None)
        if not batch or batch.role not in ("settlement_order","settlement_line"):return
        changed=[r for r in w.records.values() if r.batch_id==batch.id]
    elif e.kind in ("exclude","undo_exclude"):
        r=w.records.get(e.data.get("row"))
        changed=[r] if r and r.role in ("settlement_order","settlement_line") else []
    else:return
    orders={(r.party,r.reference if r.role=="settlement_order" else r.extra.get("order")) for r in changed}
    groups={group_id(r.party,r.extra["settlement"]) for r in changed if r.role=="settlement_line"}
    if orders:
        groups.update(group_id(r.party,r.extra["settlement"]) for r in w.records.values() if r.id in s.visible and r.role=="settlement_line" and r.extra.get("order") and (r.party,r.extra["order"]) in orders)
    for key in groups:s.net_versions[key]=s.net_versions.get(key,0)+1


def occupied_net(s):
    return {rid for p in s.net_settlements.values() for name in ("rows","orders","banks") for rid in p[name]}


def net_settlement_reports(w,period=None,state=None):
    s=state or w.state;period=period or s.period
    if period in s.closings:return deepcopy(s.closings[period].get("net_settlements",[]))
    if period!=s.period:fail("只可查看当前期间或已保存的历史期间")
    active=active_records(w,s)
    order_map={(r.party,r.reference):r for r in active.values() if r.role=="settlement_order"}
    grouped=defaultdict(list);sales=defaultdict(int);refunds=defaultdict(int)
    for r in active.values():
        if r.role!="settlement_line":continue
        grouped[r.party,r.extra["settlement"]].append(r)
        order=(r.party,r.extra.get("order",""))
        if r.extra["category"]=="销售":sales[order]+=r.amount_minor
        elif r.extra["category"]=="退款":refunds[order]+=-r.amount_minor
    result=[]
    for (party,settlement),rows in sorted(grouped.items()):
        rows=sorted(rows,key=lambda r:r.id);key=group_id(party,settlement)
        issues=[];orders=[];checks=[]
        refs=sorted({r.extra["order"] for r in rows if r.extra.get("order")})
        for ref in refs:
            order=order_map.get((party,ref));sale=sales[party,ref];refund=refunds[party,ref]
            if order is None:issues.append("未找到原订单："+ref)
            else:
                orders.append(order.id)
                if sale>order.amount_minor:issues.append("累计销售结算超过订单金额："+ref)
            if refund>sale:issues.append("累计退款超过已结算销售："+ref)
            checks.append({"reference":ref,"record":order.id if order else "","order_minor":order.amount_minor if order else None,"settled_minor":sale,"refunded_minor":refund,"remaining_minor":order.amount_minor-sale if order else None})
        income=sum(r.amount_minor for r in rows if r.extra["category"]=="销售")
        refunded=-sum(r.amount_minor for r in rows if r.extra["category"]=="退款")
        fees=-sum(r.amount_minor for r in rows if r.extra["category"] in ("佣金","运费","其他扣款"))
        other=sum(r.amount_minor for r in rows if r.extra["category"]=="其他加款")
        net=income-refunded-fees+other
        previous=s.net_settlements.get(key)
        banks=tuple(previous["banks"]) if previous else ()
        bank=sum(w.records[rid].amount_minor for rid in banks) if previous else None
        valid=bool(previous and previous["version"]==s.net_versions.get(key,0) and tuple(previous["rows"])==tuple(r.id for r in rows) and tuple(previous["orders"])==tuple(sorted(orders)) and previous.get("order_fingerprint")==_order_fingerprint(checks) and not issues and all(rid in active for rid in banks) and bank==net)
        status="结算内容已变化需复核" if previous and not valid else "订单依据待核实" if issues else "已确认净到账" if valid else "待关联银行流水"
        result.append({"id":key,"party":party,"settlement":settlement,"period":period,"income_minor":income,"refund_minor":refunded,"fee_minor":fees,"other_minor":other,"net_minor":net,"bank_minor":bank,"difference_minor":bank-net if bank is not None else None,"status":status,"issues":tuple(issues),"rows":tuple(r.id for r in rows),"orders":tuple(sorted(orders)),"banks":banks,"evidence":previous["evidence"] if previous else "","review_valid":valid,"order_checks":checks})
    return result


def apply_net_settlement(w,s,e,active):
    d=e.data
    if e.kind=="undo_net_settlement":
        target=d.get("target");_note(d,"note",True)
        if not isinstance(target,str) or target not in s.net_settlements:fail("结算确认不存在或已撤销")
        del s.net_settlements[target]
        return
    group=d.get("group")
    report=next((p for p in net_settlement_reports(w,state=s) if p["id"]==group),None)
    if not report:fail("请选择当前可用的结算批次")
    evidence=_note(d,"evidence",True)
    banks=() if d.get("banks")==[] and report["net_minor"]==0 else _ids(d.get("banks"),w.records,active)
    bankrows=[active[rid] for rid in banks]
    if any(r.role!="bank" for r in bankrows) or (bankrows and len({r.account for r in bankrows})!=1):fail("请选择同一本企业人民币账户的银行流水")
    if any(set(banks).intersection(p["banks"]) for key,p in s.net_settlements.items() if key!=group):fail("银行流水已被另一结算批次确认使用")
    if report["issues"]:fail("原订单或退款依据存在待核实问题，不能确认净到账")
    if sum(r.amount_minor for r in bankrows)!=report["net_minor"]:fail("银行净到账与结算构成不一致，请先核实差额")
    s.net_settlements[group]={"banks":banks,"rows":report["rows"],"orders":report["orders"],"version":s.net_versions.get(group,0),"order_fingerprint":_order_fingerprint(report["order_checks"]),"evidence":evidence,"period":s.period}
