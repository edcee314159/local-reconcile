"""Synthetic evidence-chain, 30/60/10 contract and correction examples."""
from dataclasses import replace
from pathlib import Path
from .demo import _raw
from .workspace import new_workspace, add_account, add_batch, record_event
from .evidence_chain import evidence_report
from .contract_terms import contract_report
from ..domain import MappingSpec


def audit_demo():
    w = add_account(new_workspace("2026-10"), "DEMO-AUDIT", "虚构审计银行")
    party = "虚构合同客户"
    evidence_rows = [
        ["2026-10-01", "1000", party, "CONTRACT-AUDIT", "虚构合同总额1000元", "AUDIT-COMPLETE", "合同", "应收"],
        ["2026-10-20", "1000", party, "ACCEPT-AUDIT", "虚构人工验收凭证", "AUDIT-COMPLETE", "验收", "应收"],
        ["2026-10-21", "1000", party, "INVOICE-AUDIT", "虚构开票凭证", "AUDIT-COMPLETE", "发票", "应收"],
        ["2026-10-05", "300", party, "RECEIPT-AUDIT", "虚构首期收款凭证", "AUDIT-COMPLETE", "收款", "应收"],
        ["2026-10-02", "200", "虚构待补证客户", "CONTRACT-MISSING", "虚构缺验收案例", "AUDIT-MISSING", "合同", "应收"],
    ]
    raw = replace(_raw("ledger", "虚构审计-业务凭证.csv", evidence_rows), headers=("日期", "金额", "单位", "编号", "摘要", "业务组", "凭证类别", "方向"))
    mapping = MappingSpec(party_col=2, reference_col=3, summary_col=4, declared_account="OPEN-ITEMS", confirmed=True)
    w = add_batch(w, "business_evidence", "", raw, mapping, extra_cols={"business": 5, "kind": 6, "direction": 7})
    raw = _raw("bank", "虚构审计-银行.csv", [["2026-10-05", "300", party, "BANK-AUDIT", "虚构首期到账"]])
    w = add_batch(w, "bank", "DEMO-AUDIT", raw, replace(mapping, declared_account="DEMO-AUDIT"))
    raw = _raw("ledger", "虚构审计-应收.csv", [
        ["2026-10-01", "1000", party, "AR-WRONG", "虚构演示：首款误选的单据"],
        ["2026-10-02", "1000", party, "AR-CORRECT", "虚构演示：应改为此单据"],
    ])
    w = add_batch(w, "receivable", "", raw, mapping)
    ids = {r.reference: r.id for r in w.records.values()}
    for group in evidence_report(w)["groups"]:
        required = ["合同", "验收", "发票", "收款"] if group["business"] == "AUDIT-COMPLETE" else ["合同", "验收"]
        w = record_event(w, "register_evidence_rule", group=group["id"], required=required, contract=group["contract"], evidence="虚构人工核实：本业务所需凭证类别")
    w = record_event(w, "link_evidence_cash", document=ids["RECEIPT-AUDIT"], cash=ids["BANK-AUDIT"], amount_minor=30000, evidence="虚构收款凭证与银行300元对应")
    complete = next(p for p in evidence_report(w)["groups"] if p["business"] == "AUDIT-COMPLETE")
    w = record_event(w, "confirm_evidence_chain", group=complete["id"], evidence="虚构逐项核对合同、验收、发票和银行收款")
    for name, amount, trigger, delay in (("首款30%", 30000, "签约", 4), ("验收款60%", 60000, "验收", 10), ("质保尾款10%", 10000, "质保届满", 365)):
        w = record_event(w, "register_contract_stage", contract=ids["CONTRACT-AUDIT"], name=name, amount_minor=amount, trigger=trigger, base_day="", delay_days=delay, evidence="虚构合同分阶段结算条款，金额已人工确认")
    for key, stage in list(w.state.contract_stages.items()):
        if stage["trigger"] in ("验收", "质保届满"):
            w = record_event(w, "verify_stage_condition", stage=key, document=ids["ACCEPT-AUDIT"], evidence="虚构人工核实：该验收凭证作为本阶段的起算依据")
        else:
            w = record_event(w, "link_stage_cash", stage=key, cash=ids["BANK-AUDIT"], amount_minor=30000, kind="结算", evidence="虚构首款300元银行证明；仅证明关联")
    return record_event(w, "allocate", cash=ids["BANK-AUDIT"], item=ids["AR-WRONG"], amount_minor=30000, note="虚构首款误选单据，供更正预览演示")


def run_audit_smoke(output):
    from .corrections import preview_correction, apply_correction
    from .storage import save_workspace, load_workspace, export_workspace
    from .settlements import item_used
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    w = audit_demo()
    old_evidence = evidence_report(w); old_contracts = contract_report(w)
    w = record_event(record_event(w, "close_period"), "advance_period", period="2026-11")
    allocation = next(iter(w.state.allocations)); original = w.state.allocations[allocation]
    correct = next(r.id for r in w.records.values() if r.reference == "AR-CORRECT")
    wrong = original["item"]
    operations = [
        {"kind": "undo_allocate", "data": {"target": allocation, "note": "虚构更正：原核销选错单据"}},
        {"kind": "allocate", "data": {"cash": original["cash"], "item": correct, "amount_minor": 30000, "note": "虚构更正：首款改核销正确单据"}},
    ]
    reason = "虚构演示：首款金额不变，更正其核销单据"
    events = w.events
    preview = preview_correction(w, operations, reason)
    if not preview["ok"] or w.events != events:
        raise RuntimeError("audit correction preview failed or changed its source")
    w = apply_correction(w, preview, reason)
    if item_used(w.state, wrong) or item_used(w.state, correct) != 30000 or len(w.state.corrections) != 1:
        raise RuntimeError("audit correction did not move exactly one 300 yuan allocation")
    if evidence_report(w, "2026-10") != old_evidence or contract_report(w, "2026-10") != old_contracts:
        raise RuntimeError("audit historical evidence or contracts changed")
    path = output / "audit-demo.lrwork"
    save_workspace(w, path); restored = load_workspace(path)
    if restored.state != w.state:
        raise RuntimeError("audit workspace replay differs after storage")
    export_workspace(restored, output / "audit-report.xlsx")
    contracts = contract_report(restored)
    return {"evidence_chain_confirmed": any(p["review_valid"] for p in evidence_report(restored)["groups"]),
            "contract_stage_count": len(contracts["stages"]), "contract_paid_minor": sum(p["paid_minor"] for p in contracts["stages"]),
            "correction_audit_count": len(restored.state.corrections), "audit_history_preserved": True}
