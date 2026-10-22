"""Contract proof is explicit, bounded and independent from financial posting."""
from copy import deepcopy
import pytest
from conftest import raw_table, mapping
from local_reconcile.domain import LocalReconcileError
from local_reconcile.business.workspace import new_workspace, add_account, add_batch, record_event


def source(w, kind, amount="100", reference="C1", day="2026-10-01", party="甲", business="G1", direction="应收"):
    raw = raw_table("ledger", [[day, amount, party, reference, "", business, kind, direction]],
                    ("日期", "金额", "对方", "编号", "摘要", "业务组", "类别", "方向"))
    return add_batch(w, "business_evidence", "", raw, mapping(declared_account="OPEN-ITEMS"),
                     extra_cols={"business": 5, "kind": 6, "direction": 7})


def base(direction="应收", period="2026-10", day="2026-10-01", amount="100"):
    return source(add_account(new_workspace(period), "A", "银行"), "合同", amount, day=day, direction=direction)


def rid(w, reference):
    return next(r.id for r in w.records.values() if r.reference == reference)


def bank(w, amount="100", reference="B1", day="2026-10-15"):
    return add_batch(w, "bank", "A", raw_table("bank", [[day, amount, "甲", reference, ""]]), mapping(declared_account="A"))


def stage(w, name="首款", amount=3000, trigger="签约", delay=0, base_day="", contract="C1", evidence="合同条款核实"):
    return record_event(w, "register_contract_stage", contract=rid(w, contract), name=name, amount_minor=amount,
                        trigger=trigger, base_day=base_day, delay_days=delay, evidence=evidence)


def sid(w, name="首款"):
    return next(k for k, p in w.state.contract_stages.items() if p["name"] == name)


def report(w, period=None):
    from local_reconcile.business.contract_terms import contract_report
    return contract_report(w, period)


def row(w, name="首款"):
    return next(p for p in report(w)["stages"] if p["name"] == name)


def verify(w, reference="D1", name="首款", evidence="验收条款已核实"):
    return record_event(w, "verify_stage_condition", stage=sid(w, name), document=rid(w, reference), evidence=evidence)


def pay(w, amount=1000, reference="B1", name="首款", kind="结算", evidence="已核实银行证明"):
    return record_event(w, "link_stage_cash", stage=sid(w, name), cash=rid(w, reference), amount_minor=amount, kind=kind, evidence=evidence)


def undo(w, kind, target):
    return record_event(w, kind, target=target, note="更正凭证依据")


def test_visible_contract_without_plan_is_reported():
    r = report(base())["contracts"][0]
    assert (r["amount_minor"], r["planned_minor"], r["paid_minor"], r["remaining_minor"], r["unplanned_minor"], r["stage_count"]) == (10000, 0, 0, 10000, 10000, 0)
    assert "阶段计划尚未完整登记" in r["flags"]


def test_30_60_10_plan_conserves_face_and_rejects_excess_and_duplicate_names():
    w = stage(stage(stage(base()), "验收款", 6000, "验收"), "尾款", 1000, "质保届满", 365)
    assert report(w)["contracts"][0]["planned_minor"] == 10000
    assert not report(w)["contracts"][0]["unplanned_minor"]
    with pytest.raises(LocalReconcileError): stage(w, "超额", 1)
    with pytest.raises(LocalReconcileError): stage(w, "首款", 1)


@pytest.mark.parametrize("changes", [dict(amount=0), dict(amount=True), dict(amount=1.2), dict(name=" "), dict(trigger="推断日期"), dict(delay=-1), dict(delay=36501), dict(delay=True), dict(evidence=" "), dict(trigger="验收", base_day="2026-10-10"), dict(trigger="自定日期", base_day="2026-09-30"), dict(trigger="自定日期", base_day="2026-2-1")])
def test_invalid_stage_parameters_are_rejected(changes):
    w = base()
    with pytest.raises(LocalReconcileError): stage(w, **changes)


def test_stage_requires_active_positive_contract_source():
    w = source(base(), "订单", reference="O1")
    with pytest.raises(LocalReconcileError): stage(w, contract="O1")
    w = record_event(w, "exclude", row=rid(w, "C1"), note="来源核实")
    with pytest.raises(LocalReconcileError): stage(w)


def test_signing_and_custom_due_dates_respect_due_today_and_leap_day():
    w = stage(base(period="2024-02", day="2024-02-28"), delay=1)
    assert (row(w)["due_day"], row(w)["overdue_days"], row(w)["status"]) == ("2024-02-29", 0, "已到期未结清")
    w = stage(w, "自定", 1000, "自定日期", 1, "2024-02-29")
    assert (row(w, "自定")["due_day"], row(w, "自定")["status"]) == ("2024-03-01", "未到期")


@pytest.mark.parametrize("trigger", ["到货", "验收", "开票", "质保届满"])
def test_unknown_milestone_has_no_fabricated_due_or_overdue(trigger):
    p = row(stage(base(), trigger=trigger, delay=10))
    assert p["due_day"] is None and p["overdue_days"] is None
    assert p["status"] == "条件未核实" and p["condition_document"] == ""


@pytest.mark.parametrize("trigger,kind", [("到货", "收货"), ("验收", "验收"), ("开票", "发票"), ("质保届满", "验收")])
def test_verified_matching_document_establishes_due(trigger, kind):
    w = source(stage(base(), trigger=trigger, delay=2), kind, reference="D1", day="2026-10-20")
    p = row(verify(w))
    assert (p["due_day"], p["overdue_days"], p["status"]) == ("2026-10-22", 9, "已到期未结清")
    assert p["condition_document"] == rid(w, "D1") and p["condition_evidence"]


@pytest.mark.parametrize("kwargs", [dict(kind="收货"), dict(kind="验收", party="乙"), dict(kind="验收", business="G2"), dict(kind="验收", direction="应付"), dict(kind="验收", day="2026-09-30")])
def test_condition_rejects_wrong_type_group_party_direction_and_earlier_day(kwargs):
    w = source(stage(base(), trigger="验收"), reference="D1", **kwargs)
    with pytest.raises(LocalReconcileError): verify(w)


def test_credit_invoice_cannot_establish_condition_and_signing_needs_none():
    w = source(stage(base(), trigger="开票"), "发票", "-1", "D1")
    with pytest.raises(LocalReconcileError): verify(w)
    w = source(stage(base()), "验收", reference="D1")
    with pytest.raises(LocalReconcileError): verify(w)
    w = stage(base(), trigger="验收")
    w = source(w, "验收", reference="D1")
    with pytest.raises(LocalReconcileError): verify(w, evidence=" ")


def test_known_and_verified_calendar_overflow_are_rejected():
    boundary = base(period="9999-12", day="9999-12-31")
    with pytest.raises(LocalReconcileError): stage(boundary, delay=1)
    w = source(stage(base(period="9999-12", day="9999-12-01"), trigger="验收", delay=1), "验收", reference="D1", day="9999-12-31")
    with pytest.raises(LocalReconcileError): verify(w)
    assert row(w)["due_day"] is None


@pytest.mark.parametrize("direction,settlement,refund", [("应收", "100", "-100"), ("应付", "-100", "100")])
def test_partial_settlement_and_refund_preserve_direction_and_net(direction, settlement, refund):
    w = bank(bank(stage(base(direction)), settlement), refund, "B2")
    w = pay(w, 2000)
    w = pay(w, 500, "B2", kind="退回")
    p = row(w)
    assert (p["paid_minor"], p["remaining_minor"]) == (1500, 1500)
    assert "存在退回" in p["flags"] and len(p["links"]) == 2
    assert report(w)["contracts"][0]["remaining_minor"] == 8500
    assert not w.state.allocations and not w.state.advances


def test_payment_rejects_sign_bad_amount_kind_and_missing_evidence():
    w = bank(stage(base()), "-100")
    with pytest.raises(LocalReconcileError): pay(w)
    w = bank(stage(base()))
    for kwargs in (dict(amount=0), dict(amount=True), dict(amount=1.5), dict(kind="未知"), dict(evidence=" "), dict(amount=3001)):
        with pytest.raises(LocalReconcileError): pay(w, **kwargs)
    with pytest.raises(LocalReconcileError): pay(w, kind="退回")


def test_bank_proof_cannot_be_reused_beyond_face_across_contracts():
    w = source(bank(stage(base(), amount=10000), "100"), "合同", reference="C2", business="G2")
    w = stage(w, "第二合同", 10000, contract="C2")
    w = pay(w, 6000)
    w = pay(w, 4000, name="第二合同")
    with pytest.raises(LocalReconcileError): pay(w, 1, name="第二合同")
    assert sum(p["paid_minor"] for p in report(w)["contracts"]) == 10000


def test_unverified_and_early_payment_are_preserved_with_warnings():
    w = pay(bank(stage(base(), trigger="验收")))
    assert row(w)["paid_minor"] == 1000 and "未核实条件已有收付款" in row(w)["flags"]
    w = pay(bank(stage(base(), delay=30), day="2026-10-10"))
    assert "提前收付" in row(w)["flags"]


def test_undo_condition_retains_payment_and_requires_source_dependencies_first():
    w = pay(bank(verify(source(stage(base(), trigger="验收"), "验收", reference="D1"))))
    with pytest.raises(LocalReconcileError): undo(w, "undo_contract_stage", sid(w))
    with pytest.raises(LocalReconcileError): record_event(w, "exclude", row=rid(w, "C1"), note="更正")
    with pytest.raises(LocalReconcileError): record_event(w, "exclude", row=rid(w, "D1"), note="更正")
    with pytest.raises(LocalReconcileError): record_event(w, "exclude", row=rid(w, "B1"), note="更正")
    w = undo(w, "undo_stage_condition", sid(w))
    assert row(w)["due_day"] is None and row(w)["paid_minor"] == 1000
    assert "未核实条件已有收付款" in row(w)["flags"]


def test_undo_settlement_below_refund_or_refund_above_face_is_rejected():
    w = bank(bank(stage(base()), "100"), "-100", "B2")
    w = pay(w, 3000); settlement = next(iter(w.state.stage_cash_links))
    w = pay(w, 1000, "B2", kind="退回"); refund = next(k for k in w.state.stage_cash_links if k != settlement)
    with pytest.raises(LocalReconcileError): undo(w, "undo_stage_cash", settlement)
    w = pay(w, 1000)
    with pytest.raises(LocalReconcileError): undo(w, "undo_stage_cash", refund)
    assert row(w)["paid_minor"] == 3000


def test_undo_sequence_releases_occupancy_and_requires_notes():
    from local_reconcile.business.contract_terms import occupied_contracts
    w = pay(bank(stage(base())))
    link = next(iter(w.state.stage_cash_links))
    for kind, target in (("undo_stage_cash", link), ("undo_contract_stage", sid(w))):
        with pytest.raises(LocalReconcileError): record_event(w, kind, target=target, note=" ")
    assert {rid(w, "C1"), rid(w, "B1")} <= occupied_contracts(w.state)
    w = undo(w, "undo_stage_cash", link)
    w = undo(w, "undo_contract_stage", sid(w))
    assert not occupied_contracts(w.state) and not report(w)["stages"]


def test_historical_snapshot_is_immutable_and_workspace_roundtrips(tmp_path):
    from local_reconcile.business.storage import save_workspace, load_workspace
    w = pay(bank(stage(base())))
    before = deepcopy(report(w))
    original_link = next(iter(w.state.stage_cash_links))
    assert before["stages"][0]["cash_link_details"][original_link]["amount_minor"] == 1000
    w = record_event(w, "set_closing_balances", account="A", bank_minor=10000, ledger_minor=0, evidence="月末核实")
    w = record_event(record_event(w, "close_period"), "advance_period", period="2026-11")
    assert report(w, "2026-10") == before
    w = pay(bank(w, "20", "B2", "2026-11-03"), 1000, "B2")
    assert report(w, "2026-10") == before and row(w)["paid_minor"] == 2000
    w = undo(w, "undo_stage_cash", original_link)
    assert row(w)["paid_minor"] == 1000 and report(w, "2026-10") == before
    assert original_link not in w.state.stage_cash_links
    assert report(w, "2026-10")["stages"][0]["cash_link_details"][original_link]["evidence"]
    detached = report(w, "2026-10"); detached["stages"][0]["paid_minor"] = 999
    detached["stages"][0]["cash_link_details"][original_link]["amount_minor"] = 999
    assert report(w, "2026-10") == before
    path = tmp_path / "contracts.json"; save_workspace(w, path)
    restored = load_workspace(path)
    assert report(restored) == report(w) and report(restored, "2026-10") == before



def test_report_rejects_unsaved_period_and_legacy_snapshot_is_detached_empty():
    w = base()
    with pytest.raises(LocalReconcileError): report(w, "2026-09")
    from local_reconcile.business.contract_terms import contract_report
    state = deepcopy(w.state); state.closings["2026-09"] = {}
    old = contract_report(w, "2026-09", state=state)
    assert old == {"period": "2026-09", "contracts": [], "stages": []}
    old["contracts"].append("mutated")
    assert contract_report(w, "2026-09", state=state)["contracts"] == []


def test_maximum_stage_count_and_large_integer_cents_remain_exact():
    w = base(amount="90071992547409.93")
    for index in range(100):
        w = stage(w, name=f"阶段{index}", amount=1)
    with pytest.raises(LocalReconcileError): stage(w, "第101阶段", 1)
    summary = report(w)["contracts"][0]
    assert summary["amount_minor"] == 9007199254740993
    assert summary["planned_minor"] == 100 and summary["unplanned_minor"] == 9007199254740893



def test_contract_evidence_and_financial_allocation_do_not_double_post_cash():
    from local_reconcile.business.settlements import cash_free, item_used
    w = bank(stage(base(), amount=10000))
    w = source(w, "收款", reference="R1")
    w = add_batch(w, "receivable", "", raw_table("ledger", [["2026-10-01", "100", "甲", "AR1", ""]]), mapping(declared_account="OPEN-ITEMS"))
    cash = rid(w, "B1"); item = rid(w, "AR1")
    w = record_event(w, "link_evidence_cash", document=rid(w, "R1"), cash=cash, amount_minor=10000, evidence="凭证资金证明")
    w = pay(w, 10000)
    link = next(iter(w.state.stage_cash_links))
    assert cash_free(w, w.state, cash) == 10000 and item_used(w.state, item) == 0
    w = record_event(w, "allocate", cash=cash, item=item, amount_minor=10000, note="实际往来核销")
    assert cash_free(w, w.state, cash) == 0 and item_used(w.state, item) == 10000
    assert row(w)["paid_minor"] == 10000
    w = undo(w, "undo_stage_cash", link)
    assert row(w)["paid_minor"] == 0 and item_used(w.state, item) == 10000
    assert cash_free(w, w.state, cash) == 0 and len(w.state.evidence_cash_links) == 1


def test_condition_update_changes_due_and_future_document_requires_activation():
    w = source(stage(base(), trigger="验收", delay=2), "验收", reference="FUTURE", day="2026-11-01")
    with pytest.raises(LocalReconcileError): verify(w, "FUTURE")
    w = source(w, "验收", reference="D1", day="2026-10-10")
    w = pay(bank(verify(w), day="2026-10-15"))
    assert row(w)["due_day"] == "2026-10-12" and "提前收付" not in row(w)["flags"]
    w = source(w, "验收", reference="D2", day="2026-10-20")
    w = verify(w, "D2", evidence="验收日期重新核实")
    assert row(w)["due_day"] == "2026-10-22" and "提前收付" in row(w)["flags"]
    assert row(w)["condition_document"] == rid(w, "D2") and row(w)["paid_minor"] == 1000
