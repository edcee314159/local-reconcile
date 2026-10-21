"""Entirely fictional examples for credit, duplicate and partner workflows."""
from .demo import _raw
from .workspace import new_workspace, add_account, add_batch, record_event
from ..domain import MappingSpec, LocalReconcileError
from .credits import credit_rows
from .duplicates import duplicate_groups
from .counterparty import counterparty_report
from .operations import open_items


def commercial_demo():
    w = add_account(new_workspace("2026-10"), "DEMO-C", "虚构商业示例银行")
    inputs = [
        ("receivable", [["2026-10-01", "100", "虚构客户甲", "INV-C1", "原销售"], ["2026-10-02", "30", "虚构客户甲", "INV-C2", "本企业独有"]]),
        ("payable", [["2026-10-01", "200", "虚构供应商乙", "INV-P1", "原采购"]]),
        ("receivable_credit", [["2026-10-10", "-20", "虚构客户甲", "CREDIT-C1", "销售退货"]]),
        ("payable_credit", [["2026-10-11", "50", "虚构供应商乙", "CREDIT-P1", "采购折让"]]),
        ("bank", [["2026-10-20", "10", "虚构重复示例单位", "DUP-1", "第一份导出"]]),
        ("bank", [["2026-10-20", "10", "虚构重复示例单位", "DUP-1", "另一份导出，待核实"]]),
        ("partner_receivable", [["2026-10-01", "80", "虚构客户甲", "INV-C1", "对方期末余额"], ["2026-10-03", "10", "虚构客户甲", "OTHER-1", "对方独有"]]),
        ("partner_payable", [["2026-10-01", "140", "虚构供应商乙", "INV-P1", "对方期末余额有差额"]]),
    ]
    for n, (role, rows) in enumerate(inputs):
        account = "DEMO-C" if role == "bank" else ""
        raw = _raw("bank" if role == "bank" else "ledger", f"虚构商业-{n}-{role}.csv", rows)
        mapping = MappingSpec(party_col=2, reference_col=3, summary_col=4, declared_account=account or "OPEN-ITEMS", confirmed=True)
        w = add_batch(w, role, account, raw, mapping)
    return w


def run_commercial_smoke(output):
    from .storage import save_workspace, load_workspace, export_workspace
    w = commercial_demo()
    def rid(role, ref):
        return next(r.id for r in w.records.values() if r.role == role and r.reference == ref)
    for role, ref, amount, category in (("receivable", "INV-C1", 2000, "退货"), ("payable", "INV-P1", 5000, "折让")):
        credit = next(r.id for r in w.records.values() if r.role == role+"_credit")
        w = record_event(w, "apply_credit_note", credit=credit, item=rid(role, ref), amount_minor=amount, category=category, evidence="虚构红字退货折让凭据")
    group = duplicate_groups(w)[0]
    blocked = False
    try:
        record_event(w, "register_advance", cash=group["rows"][0], amount_minor=100, evidence="应阻止")
    except LocalReconcileError:
        blocked = True
    if not blocked:
        raise RuntimeError("duplicate guard did not block use")
    w = record_event(w, "exclude", row=group["rows"][1], note="虚构核实：重复导出，保留原始行")
    for batch in w.batches:
        if not batch.role.startswith("partner_"): continue
        w = record_event(w, "register_partner_statement", batch=batch.id, as_of="2026-10-31", evidence="虚构月末对账单")
        for row in counterparty_report(w, batch.id)["rows"]:
            equal = row["own"] and row["partner"] and row["own_minor"] == row["partner_minor"]
            w = record_event(w, "decide_partner", batch=batch.id, own=row["own"], partner=row["partner"], kind="confirmed" if equal else "explained", evidence="虚构逐笔核实，差异保留待处理")
    reports = {b.id: counterparty_report(w,b.id) for b in w.batches if b.role.startswith("partner_")}
    remain = {r["record"].reference:r["remaining_minor"] for r in open_items(w)}
    w = record_event(w, "close_period")
    w = record_event(w, "advance_period", period="2026-11")
    w = record_event(w, "undo_credit_note", target=next(iter(w.state.credits)), note="虚构次月更正")
    if any(counterparty_report(w,bid,"2026-10") != report for bid,report in reports.items()):
        raise RuntimeError("partner history changed")
    path = output/"commercial-demo.lrwork"
    save_workspace(w,path)
    restored = load_workspace(path)
    if restored.state != w.state: raise RuntimeError("commercial replay mismatch")
    export_workspace(restored,output/"commercial-report.xlsx")
    return {"credit_receivable_remaining_minor":remain["INV-C1"], "credit_payable_remaining_minor":remain["INV-P1"],
            "duplicate_use_blocked":blocked,"duplicate_groups_after_exclusion":len(duplicate_groups(restored)),
            "partner_confirmed_rows":sum(r["confirmed_count"] for r in reports.values()),
            "partner_explained_rows":sum(r["explained_count"] for r in reports.values()),"partner_history_preserved":True}
