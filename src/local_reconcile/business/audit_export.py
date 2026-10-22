"""Flat audit reports; the shared put callback escapes spreadsheet formulas."""
import json
from .evidence_chain import evidence_report
from .contract_terms import contract_report
from ..amounts import format_amount
from ..domain import check_cancel

HEADERS = {
    "业务证据链": ["期间", "组编号", "单位", "业务组", "方向", "合同来源", "合同限额（元）", "发票净额（元）", "凭证收付净额（元）", "银行核实净额（元）", "未关联资金（元）", "必需凭证", "缺少凭证", "状态", "检查提示", "规则依据", "确认依据", "确认有效"],
    "业务凭证明细": ["期间", "组编号", "来源记录", "凭证类别", "业务组", "方向", "日期", "金额（元）", "单位", "凭证编号", "摘要", "原文件", "源行"],
    "凭证资金关联": ["期间", "组编号", "关联编号", "凭证来源", "凭证类别", "银行来源", "账户", "银行日期", "银行金额（元）", "证明金额（元）", "关联依据", "登记期间", "原文件", "源行"],
    "合同阶段汇总": ["期间", "合同来源", "单位", "业务组", "方向", "合同编号", "合同金额（元）", "计划金额（元）", "收付净额（元）", "合同剩余（元）", "未计划金额（元）", "阶段数", "检查提示"],
    "合同阶段明细": ["期间", "阶段编号", "合同来源", "单位", "业务组", "方向", "阶段名称", "触发条件", "基准日期", "延后天数", "阶段金额（元）", "收付净额（元）", "剩余金额（元）", "到期日", "条件凭证", "条件核实依据", "状态", "逾期天数", "检查提示", "条款依据"],
    "阶段收付证明": ["期间", "阶段编号", "合同来源", "关联编号", "银行来源", "账户", "银行日期", "银行金额（元）", "类别", "阶段净收付（元）", "关联依据", "登记期间", "原文件", "源行"],
    "业务更正审计": ["期间", "更正编号", "更正原因", "原工作区指纹", "操作数", "内容分段序号", "内容分段总数", "操作JSON分段"],
}


def export_audit(w, s, put, cancelled):
    check_cancel(cancelled)
    batches = {b.id: b for b in w.batches}
    raws = {b.id: {r.id: r for r in b.raw.rows} for b in w.batches}
    def source(rid):
        r = w.records[rid]; b = batches[r.batch_id]
        return r, b.raw.filename, raws[b.id][r.source_id].source_line
    def money(value):
        return format_amount(value) if value is not None else "未确认"
    def direction(value):
        return {"receivable": "应收", "payable": "应付"}.get(value, value)
    periods = sorted(s.closings)
    if s.period not in periods:
        periods.append(s.period)
    for period in periods:
        check_cancel(cancelled)
        evidence = evidence_report(w, period, state=s)
        contracts = contract_report(w, period, state=s)
        for p in evidence["groups"]:
            check_cancel(cancelled)
            put("业务证据链", [period, p["id"], p["party"], p["business"], direction(p["direction"]), p["contract"], money(p["limit_minor"]), money(p["invoice_minor"]), money(p["declared_paid_minor"]), money(p["verified_paid_minor"]), money(p["cash_unlinked_minor"]), "、".join(p.get("required", ())), "、".join(p["missing"]), p["status"], "；".join(p["flags"]), p["evidence"], p["confirmation_evidence"], "是" if p["review_valid"] else "否"])
            for rid in p["rows"]:
                check_cancel(cancelled)
                r, filename, line = source(rid)
                put("业务凭证明细", [period, p["id"], rid, r.extra["kind"], r.extra["business"], direction(r.extra["direction"]), r.day, money(r.amount_minor), r.party, r.reference, r.summary, filename, line])
            for key, link in p.get("cash_link_details", {}).items():
                check_cancel(cancelled)
                cash, filename, line = source(link["cash"])
                doc = w.records[link["document"]]
                put("凭证资金关联", [period, p["id"], key, doc.id, doc.extra["kind"], cash.id, cash.account, cash.day, money(cash.amount_minor), money(link["amount_minor"]), link["evidence"], link["period"], filename, line])
        for p in contracts["contracts"]:
            check_cancel(cancelled)
            put("合同阶段汇总", [period, p["contract"], p["party"], p["business"], direction(p["direction"]), p["reference"], money(p["amount_minor"]), money(p["planned_minor"]), money(p["paid_minor"]), money(p["remaining_minor"]), money(p["unplanned_minor"]), p["stage_count"], "；".join(p["flags"])])
        for p in contracts["stages"]:
            check_cancel(cancelled)
            put("合同阶段明细", [period, p["id"], p["contract"], p["party"], p["business"], direction(p["direction"]), p["name"], p["trigger"], p.get("base_day", ""), p.get("delay_days", ""), money(p["amount_minor"]), money(p["paid_minor"]), money(p["remaining_minor"]), p["due_day"] or "条件未核实", p["condition_document"], p["condition_evidence"], p["status"], p["overdue_days"] if p["overdue_days"] is not None else "条件未核实", "；".join(p["flags"]), p["evidence"]])
            for key, link in p.get("cash_link_details", {}).items():
                check_cancel(cancelled)
                cash, filename, line = source(link["cash"])
                put("阶段收付证明", [period, p["id"], p["contract"], key, cash.id, cash.account, cash.day, money(cash.amount_minor), link["kind"], money(link["amount_minor"]), link["evidence"], link["period"], filename, line])
    for key, audit in s.corrections.items():
        check_cancel(cancelled)
        text = json.dumps(audit["operations"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        count = max(1, (len(text) + 29999) // 30000)
        for index in range(count):
            check_cancel(cancelled)
            put("业务更正审计", [audit["period"], key, audit["reason"], audit["base"], len(audit["operations"]), index + 1, count, text[index * 30000:(index + 1) * 30000]])
