"""Evidence-backed customer/supplier statement comparisons without financial postings."""
from copy import deepcopy
from datetime import date
from .workspace import active_records, period_end, _integer, _note, fail
from .settlements import item_used
from ..matching import stable_id

PARTNER_ROLES = {"partner_receivable": "receivable", "partner_payable": "payable"}


def _batch(w, batch_id):
    if not isinstance(batch_id, str):
        fail("请选择客户或供应商对账单批次")
    batch = next((b for b in w.batches if b.id == batch_id), None)
    if batch is None or batch.role not in PARTNER_ROLES:
        fail("请选择客户或供应商对账单批次")
    return batch


def apply_counterparty(w, s, e, active):
    d = e.data
    if e.kind == "register_partner_statement":
        batch_id = d.get("batch")
        batch = _batch(w, batch_id)
        as_of = d.get("as_of")
        try:
            if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
                raise ValueError
        except ValueError:
            fail("对账单截止日请使用 YYYY-MM-DD")
        if as_of != period_end(s.period).isoformat():
            fail("对账单截止日必须为当前期间月末")
        if batch.statement_period is not None and batch.statement_period != s.period:
            fail("对账单所属月份与当前期间不一致，请导入本月新对账单")
        previous = s.partner_statements.get(batch_id)
        if previous and previous["as_of"] != as_of:
            fail("同一对账单批次不能改作其他截止日；请导入对应期间的新对账单")
        # Do not use active_records here: it would silently hide post-cutoff rows.
        rows = [r for r in w.records.values() if r.batch_id == batch_id and r.id in s.visible]
        if not rows or any(r.day > period_end(s.period) for r in rows):
            fail("对账单来源尚未导入，或包含晚于截止日的单据")
        parties = {r.party for r in rows}
        if len(parties) != 1 or not all(parties):
            fail("每份客户或供应商对账单必须只包含一个往来单位")
        evidence = previous["evidence"] if previous and "evidence" not in d else _note(d, "evidence", True)
        s.partner_statements[batch_id] = {
            "batch": batch_id, "as_of": as_of, "party": next(iter(parties)),
            "role": PARTNER_ROLES[batch.role], "evidence": evidence, "period": s.period,
        }
    elif e.kind == "decide_partner":
        batch_id = d.get("batch")
        _batch(w, batch_id)
        result = counterparty_report(w, batch_id, state=s)
        own_id, partner_id = d.get("own"), d.get("partner")
        if not isinstance(own_id, str) or not isinstance(partner_id, str) or not (own_id or partner_id):
            fail("请选择本企业和对方对应的来源；缺失一侧须明确留空")
        own, partner = active.get(own_id), active.get(partner_id)
        if own_id and (own is None or own.role != result["role"] or own.party != result["party"]):
            fail("本企业单据不属于当前可用的对应往来单位及应收应付方向")
        if partner_id and (partner is None or partner.batch_id != batch_id or PARTNER_ROLES.get(partner.role) != result["role"] or partner.party != result["party"]):
            fail("对方来源不属于当前选定的对账单批次")
        if own and partner and own.reference != partner.reference:
            fail("本企业与对方单据编号必须完全一致")
        row = next((r for r in result["rows"] if r["own"] == own_id and r["partner"] == partner_id), None)
        if row is None:
            fail("所选来源不对应当前对账行；已有对应单据时不能将其留空")
        kind = d.get("kind")
        equal = bool(own_id and partner_id) and row["own_minor"] == row["partner_minor"]
        if kind not in ("confirmed", "explained") or (kind == "confirmed" and not equal) or (kind == "explained" and equal):
            fail("金额一致且双方单据均存在时才可确认；差异或缺单只能登记差异说明")
        evidence = _note(d, "evidence", True)
        s.partner_decisions[row["id"]] = {
            "batch": batch_id, "own": own_id, "partner": partner_id,
            "own_minor": row["own_minor"], "partner_minor": row["partner_minor"],
            "kind": kind, "evidence": evidence, "period": s.period,
            "balance_revision": s.balance_revisions.get(own_id,0),
        }
    elif e.kind == "undo_partner_decision":
        target = d.get("target")
        if not isinstance(target, str) or target not in s.partner_decisions:
            fail("该对账确认或差异说明不存在或已撤销")
        _note(d, "note", True)
        del s.partner_decisions[target]
    else:
        fail("不支持的往来对账操作")


def counterparty_report(w, batch_id, period=None, state=None):
    s = state or w.state
    period = period or s.period
    if period in s.closings:
        if not isinstance(batch_id, str):
            fail("请选择客户或供应商对账单批次")
        stored = s.closings[period].get("partner_reports", {}).get(batch_id)
        if stored is None:
            fail("所选期间没有该客户或供应商对账单的历史快照")
        return deepcopy(stored)
    if period != s.period:
        fail("只可查看当前期间或已保存的历史期间")
    _batch(w, batch_id)
    statement = s.partner_statements.get(batch_id)
    if not statement:
        fail("请先登记对账单截止日及核实依据")
    if statement["as_of"] != period_end(s.period).isoformat():
        fail("该对账单截止日不属于当前期间月末；请选择本期新对账单或查看历史快照")
    active = active_records(w, s)
    party, role = statement["party"], statement["role"]
    partner_rows = {r.reference: r for r in active.values() if r.batch_id == batch_id and r.party == party and PARTNER_ROLES.get(r.role) == role}
    own_rows = {r.reference: r for r in active.values() if r.role == role and r.party == party and (r.amount_minor - item_used(s, r.id) != 0 or r.reference in partner_rows)}
    rows = []
    for reference in sorted(set(own_rows) | set(partner_rows)):
        own, partner = own_rows.get(reference), partner_rows.get(reference)
        own_id, partner_id = own.id if own else "", partner.id if partner else ""
        own_minor = _integer(own.amount_minor - item_used(s, own.id)) if own else None
        partner_minor = _integer(partner.amount_minor) if partner else None
        row_id = stable_id("partner", batch_id, party, reference)
        decision = s.partner_decisions.get(row_id)
        decision_valid = bool(decision and decision["batch"] == batch_id and decision["own"] == own_id and decision["partner"] == partner_id and decision["own_minor"] == own_minor and decision["partner_minor"] == partner_minor and decision["period"] == period and decision.get("balance_revision",0) == s.balance_revisions.get(own_id,0))
        if decision and not decision_valid:
            status = "余额已变动需复核"
        elif decision_valid:
            status = "已确认" if decision["kind"] == "confirmed" else "差异已说明仍未核平"
        elif own is None:
            status = "仅对方有"
        elif partner is None:
            status = "仅本企业有"
        else:
            status = "金额一致待确认" if own_minor == partner_minor else "金额差异"
        rows.append({
            "id": row_id, "own": own_id, "partner": partner_id, "reference": reference,
            "own_minor": own_minor, "partner_minor": partner_minor,
            "difference_minor": (own_minor if own_minor is not None else 0) - (partner_minor if partner_minor is not None else 0),
            "status": status, "evidence": decision["evidence"] if decision else "", "decision_valid": decision_valid,
        })
    own_total = sum(r["own_minor"] for r in rows if r["own_minor"] is not None)
    partner_total = sum(r["partner_minor"] for r in rows if r["partner_minor"] is not None)
    return {
        "batch": batch_id, "period": period, "as_of": statement["as_of"], "party": party, "role": role,
        "own_total_minor": own_total, "partner_total_minor": partner_total, "difference_minor": own_total - partner_total,
        "rows": rows, "evidence": statement["evidence"],
        "confirmed_count": sum(r["status"] == "已确认" for r in rows),
        "explained_count": sum(r["status"] == "差异已说明仍未核平" for r in rows),
        "unreviewed_count": sum(not r["decision_valid"] for r in rows),
    }
