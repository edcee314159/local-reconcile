"""Explicit contract milestones and bank proof, without financial posting."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
import re

from .workspace import active_records, fail, _note, _integer, period_end


TRIGGERS = ("签约", "到货", "验收", "开票", "质保届满", "自定日期")
CONDITION_KINDS = {"到货": "收货", "验收": "验收", "开票": "发票", "质保届满": "验收"}


def _source(active, rid, role, message):
    if not isinstance(rid, str) or rid not in active or active[rid].role != role:
        fail(message)
    return active[rid]


def _contract(active, rid):
    row = _source(active, rid, "business_evidence", "请选择当前可用的合同来源")
    if row.extra.get("kind") != "合同" or row.amount_minor <= 0 or row.extra.get("direction") not in ("receivable", "payable"):
        fail("阶段计划须关联正数合同及明确应收应付方向")
    return row


def _stage(s, key):
    if not isinstance(key, str) or key not in s.contract_stages:
        fail("合同阶段不存在或已撤销")
    return s.contract_stages[key]


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        fail("自定日期请使用 YYYY-MM-DD")
    try:
        result = date.fromisoformat(value)
    except ValueError:
        fail("自定日期无效")
    if result.year < 1900:
        fail("日期年份须为 1900—9999")
    return result


def _due(w, s, key, stage):
    contract = w.records[stage["contract"]]
    if stage["trigger"] == "签约":
        base = contract.day
    elif stage["trigger"] == "自定日期":
        base = _date(stage["base_day"])
    else:
        condition = s.stage_conditions.get(key)
        if not condition:
            return None
        base = w.records[condition["document"]].day
    try:
        return base + timedelta(days=stage["delay_days"])
    except OverflowError:
        fail("阶段到期日超出支持的日历范围，请调整延后天数")


def occupied_contracts(s):
    """Source rows cannot be excluded while referenced by current proof."""
    return ({p["contract"] for p in s.contract_stages.values()}
            | {p["document"] for p in s.stage_conditions.values()}
            | {p["cash"] for p in s.stage_cash_links.values()})


def validate_stage_balances(w, s):
    """Check signed stage balances and gross use of each bank proof after undo."""
    paid = defaultdict(int)
    cash_used = defaultdict(int)
    planned = defaultdict(int)
    for stage in s.contract_stages.values():
        planned[stage["contract"]] += stage["amount_minor"]
    for contract, amount in planned.items():
        if contract not in w.records or amount > w.records[contract].amount_minor:
            fail("累计阶段计划不能超过合同金额")
    for p in s.stage_cash_links.values():
        if p["stage"] not in s.contract_stages:
            fail("收付款证明关联的阶段不存在")
        paid[p["stage"]] += p["amount_minor"]
        cash_used[p["cash"]] += abs(p["amount_minor"])
    for key, amount in paid.items():
        if not 0 <= amount <= s.contract_stages[key]["amount_minor"]:
            fail("阶段净收付款不能为负或超过阶段金额；请先处理相关退回或结算")
    for key, amount in cash_used.items():
        cash = w.records.get(key)
        if cash is None or cash.role != "bank" or amount > abs(cash.amount_minor):
            fail("银行流水的累计阶段证明金额不能超过流水金额")


def apply_contract(w, s, e, active):
    d = e.data
    if e.kind == "register_contract_stage":
        contract = _contract(active, d.get("contract"))
        name = _note(d, "name", True)
        evidence = _note(d, "evidence", True)
        amount = _integer(d.get("amount_minor"), True)
        trigger = d.get("trigger")
        delay = d.get("delay_days")
        base = d.get("base_day", "")
        if trigger not in TRIGGERS:
            fail("合同阶段触发条件无效")
        if type(delay) is not int or not 0 <= delay <= 36500:
            fail("延后天数须为 0—36500 的整数")
        if trigger == "自定日期":
            if _date(base) < contract.day:
                fail("自定日期不能早于合同日期")
        elif not isinstance(base, str) or base:
            fail("该条件的基准日期由合同或核实凭证提供，请勿手填")
        stages = [p for p in s.contract_stages.values() if p["contract"] == contract.id]
        if len(stages) >= 100:
            fail("每份合同最多登记 100 个阶段")
        if any(p["name"] == name for p in stages):
            fail("同一合同的阶段名称不能重复")
        if amount + sum(p["amount_minor"] for p in stages) > contract.amount_minor:
            fail("累计阶段计划不能超过合同金额")
        key = f"stage-{e.seq}"
        stage = {"contract": contract.id, "name": name, "amount_minor": amount, "trigger": trigger,
                 "base_day": base, "delay_days": delay, "evidence": evidence, "period": s.period,
                 "direction": contract.extra["direction"], "seq": e.seq}
        _due(w, s, key, stage)
        s.contract_stages[key] = stage
    elif e.kind == "verify_stage_condition":
        key = d.get("stage")
        stage = _stage(s, key)
        contract = _contract(active, stage["contract"])
        kind = CONDITION_KINDS.get(stage["trigger"])
        if kind is None:
            fail("签约和自定日期阶段不需要另行核实条件凭证")
        doc = _source(active, d.get("document"), "business_evidence", "请选择当前可用的条件凭证")
        if (doc.extra.get("kind") != kind or doc.party != contract.party
                or doc.extra.get("business") != contract.extra.get("business")
                or doc.extra.get("direction") != contract.extra.get("direction")):
            fail("条件凭证须匹配合同的单位、业务组、应收应付方向及触发类别")
        if doc.day < contract.day:
            fail("条件凭证日期不能早于合同日期")
        if kind == "发票" and doc.amount_minor <= 0:
            fail("红字或零额发票不能作为开票条件成立的凭证")
        evidence = _note(d, "evidence", True)
        try:
            doc.day + timedelta(days=stage["delay_days"])
        except OverflowError:
            fail("条件成立后的到期日超出支持的日历范围")
        s.stage_conditions[key] = {"document": doc.id, "evidence": evidence, "seq": e.seq, "period": s.period}
    elif e.kind == "link_stage_cash":
        key = d.get("stage")
        stage = _stage(s, key)
        contract = _contract(active, stage["contract"])
        cash = _source(active, d.get("cash"), "bank", "请选择当前可用的银行流水")
        amount = _integer(d.get("amount_minor"), True)
        kind = d.get("kind")
        if kind not in ("结算", "退回"):
            fail("阶段收付款类别须为结算或退回")
        sign = 1 if contract.extra["direction"] == "receivable" else -1
        if kind == "退回":
            sign = -sign
        if not cash.amount_minor or (cash.amount_minor > 0) != (sign > 0):
            fail("银行收付方向与合同阶段结算或退回方向不一致")
        evidence = _note(d, "evidence", True)
        signed = amount if kind == "结算" else -amount
        paid = sum(p["amount_minor"] for p in s.stage_cash_links.values() if p["stage"] == key)
        used = sum(abs(p["amount_minor"]) for p in s.stage_cash_links.values() if p["cash"] == cash.id)
        if not 0 <= paid + signed <= stage["amount_minor"]:
            fail("阶段净收付款不能为负或超过阶段金额")
        if used + amount > abs(cash.amount_minor):
            fail("银行流水的累计阶段证明金额不能超过流水金额")
        s.stage_cash_links[f"stage-cash-{e.seq}"] = {
            "stage": key, "cash": cash.id, "amount_minor": signed, "kind": kind,
            "evidence": evidence, "period": s.period}
    elif e.kind in ("undo_stage_condition", "undo_stage_cash", "undo_contract_stage"):
        _note(d, "note", True)
        target = d.get("target")
        if e.kind == "undo_stage_cash":
            if not isinstance(target, str) or target not in s.stage_cash_links:
                fail("阶段收付款证明不存在或已撤销")
            link = s.stage_cash_links[target]
            stage = _stage(s, link["stage"])
            remaining_paid = sum(p["amount_minor"] for k, p in s.stage_cash_links.items()
                                 if p["stage"] == link["stage"] and k != target)
            if not 0 <= remaining_paid <= stage["amount_minor"]:
                fail("撤销后阶段净收付款将为负或超过阶段金额；请先处理相关退回或结算")
            del s.stage_cash_links[target]
        elif e.kind == "undo_stage_condition":
            _stage(s, target)
            if target not in s.stage_conditions:
                fail("阶段条件核实记录不存在或已撤销")
            del s.stage_conditions[target]
        else:
            _stage(s, target)
            if target in s.stage_conditions or any(p["stage"] == target for p in s.stage_cash_links.values()):
                fail("请先撤销阶段条件和所有阶段收付款关联，再撤销阶段")
            del s.contract_stages[target]
    else:
        fail("合同阶段操作类型无效")
    validate_stage_balances(w, s)


def contract_report(w, period=None, state=None):
    s = state or w.state
    period = period or s.period
    if period in s.closings:
        return deepcopy(s.closings[period].get("contracts", {"period": period, "contracts": [], "stages": []}))
    if period != s.period:
        fail("只可查看当前期间或已保存的历史期间")
    active = active_records(w, s)
    asof = period_end(period)
    contracts = sorted((r for r in active.values() if r.role == "business_evidence" and r.extra.get("kind") == "合同"), key=lambda r: r.id)
    stage_rows = []
    summaries = []
    for contract in contracts:
        own = []
        for key, stage in s.contract_stages.items():
            if stage["contract"] != contract.id:
                continue
            details = {lid: deepcopy(p) for lid, p in s.stage_cash_links.items() if p["stage"] == key}
            paid = sum(p["amount_minor"] for p in details.values())
            remaining = stage["amount_minor"] - paid
            due = _due(w, s, key, stage)
            condition = s.stage_conditions.get(key, {})
            flags = []
            if due is None and any(p["amount_minor"] > 0 for p in details.values()):
                flags.append("未核实条件已有收付款")
            if due is not None and any(p["amount_minor"] > 0 and w.records[p["cash"]].day < due for p in details.values()):
                flags.append("提前收付")
            if any(p["amount_minor"] < 0 for p in details.values()):
                flags.append("存在退回")
            status = ("已结清" if remaining == 0 else "条件未核实" if due is None
                      else "未到期" if due > asof else "已到期未结清")
            result = {"id": key, "contract": contract.id, "party": contract.party,
                      "business": contract.extra["business"], "direction": contract.extra["direction"],
                      "name": stage["name"], "trigger": stage["trigger"], "amount_minor": stage["amount_minor"],
                      "paid_minor": paid, "remaining_minor": remaining, "due_day": due.isoformat() if due else None,
                      "condition_document": condition.get("document", ""), "condition_evidence": condition.get("evidence", ""),
                      "status": status, "overdue_days": max(0, (asof - due).days) if due and remaining > 0 else 0 if due else None,
                      "links": tuple(details), "cash_ids": tuple(sorted({p["cash"] for p in details.values()})),
                      "cash_link_details": details, "evidence": stage["evidence"], "period": period,
                      "flags": tuple(flags), "base_day": stage["base_day"], "delay_days": stage["delay_days"]}
            own.append(result)
        planned = sum(p["amount_minor"] for p in own)
        paid = sum(p["paid_minor"] for p in own)
        flags = (["阶段计划尚未完整登记"] if planned < contract.amount_minor else [])
        flags += sorted({flag for p in own for flag in p["flags"]})
        summaries.append({"contract": contract.id, "party": contract.party, "business": contract.extra["business"],
                          "direction": contract.extra["direction"], "reference": contract.reference,
                          "amount_minor": contract.amount_minor, "planned_minor": planned, "paid_minor": paid,
                          "remaining_minor": contract.amount_minor - paid, "unplanned_minor": contract.amount_minor - planned,
                          "stage_count": len(own), "flags": tuple(flags), "period": period})
        stage_rows.extend(own)
    return {"period": period, "contracts": summaries, "stages": stage_rows}
