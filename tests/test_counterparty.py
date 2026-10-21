from copy import deepcopy
from dataclasses import replace
from datetime import date
import pytest
from local_reconcile.domain import LocalReconcileError
from local_reconcile.business.workspace import record_event
from test_business import base, add, ids


def partner_fixture(role="receivable", own="100", stated="100"):
    w = add(base(), role, [["2026-10-01", own, "甲", "INV1", ""]])
    w = add(w, "partner_" + role, [["2026-10-25", stated, "甲", "INV1", ""]])
    bid = w.batches[-1].id
    w = record_event(w, "register_partner_statement", batch=bid, as_of="2026-10-31", evidence="对方签章对账单")
    return w, bid


def report(w, bid, **kwargs):
    from local_reconcile.business.counterparty import counterparty_report
    return counterparty_report(w, bid, **kwargs)


def decide(w, bid, kind="confirmed", own=None, partner=None, evidence="双方核实"):
    row = report(w, bid)["rows"][0]
    return record_event(w, "decide_partner", batch=bid, own=row["own"] if own is None else own,
                        partner=row["partner"] if partner is None else partner, kind=kind, evidence=evidence)


def test_kernel_is_available():
    from local_reconcile.business import counterparty
    assert callable(counterparty.apply_counterparty)
    assert callable(counterparty.counterparty_report)


@pytest.mark.parametrize("role", ["receivable", "payable"])
def test_statement_compares_each_direction_and_confirmation_is_review_only(role):
    w, bid = partner_fixture(role)
    before = deepcopy(w.state.allocations)
    result = report(w, bid)
    assert (result["role"], result["own_total_minor"], result["partner_total_minor"], result["difference_minor"]) == (role, 10000, 10000, 0)
    row = result["rows"][0]
    assert row["status"] == "金额一致待确认" and not row["decision_valid"]
    assert (row["own_minor"], row["partner_minor"]) == (10000, 10000)
    confirmed = decide(w, bid)
    row2 = report(confirmed, bid)["rows"][0]
    assert row2["status"] == "已确认" and row2["decision_valid"]
    assert confirmed.state.allocations == before
    assert confirmed.records == w.records


def test_report_tracks_exact_reference_and_missing_sides_without_guessing_zero():
    w = add(base(), "receivable", [["2026-10-01", "10", "甲", "OWN", ""], ["2026-10-01", "20", "甲", "SAME", ""], ["2026-10-01", "90", "乙", "OTHER", ""]])
    w = add(w, "partner_receivable", [["2026-10-25", "25", "甲", "SAME", ""], ["2026-10-25", "0", "甲", "PARTNER", ""]])
    bid = w.batches[-1].id
    w = record_event(w, "register_partner_statement", batch=bid, as_of="2026-10-31", evidence="签章")
    result = report(w, bid)
    rows = {r["reference"]: r for r in result["rows"]}
    assert set(rows) == {"OWN", "SAME", "PARTNER"}
    assert (rows["OWN"]["own_minor"], rows["OWN"]["partner_minor"], rows["OWN"]["partner"], rows["OWN"]["status"]) == (1000, None, "", "仅本企业有")
    assert (rows["PARTNER"]["own_minor"], rows["PARTNER"]["partner_minor"], rows["PARTNER"]["own"], rows["PARTNER"]["status"]) == (None, 0, "", "仅对方有")
    assert rows["SAME"]["status"] == "金额差异"
    assert (result["own_total_minor"], result["partner_total_minor"], result["difference_minor"]) == (3000, 2500, 500)
    for ref in ("OWN", "PARTNER"):
        row = rows[ref]
        w = record_event(w, "decide_partner", batch=bid, own=row["own"], partner=row["partner"], kind="explained", evidence="待补单")
    assert {r["reference"]: r["status"] for r in report(w, bid)["rows"]}["PARTNER"] == "差异已说明仍未核平"


def test_mismatch_cannot_be_confirmed_and_explanation_retains_difference():
    w, bid = partner_fixture(stated="90")
    with pytest.raises(LocalReconcileError):
        decide(w, bid)
    explained = decide(w, bid, "explained")
    row = report(explained, bid)["rows"][0]
    assert row["status"] == "差异已说明仍未核平" and row["difference_minor"] == 1000
    assert report(explained, bid)["difference_minor"] == 1000


@pytest.mark.parametrize("kind,stated", [("confirmed", "100"), ("explained", "90")])
def test_new_allocation_invalidates_decision_until_reverified(kind, stated):
    w, bid = partner_fixture(stated=stated)
    w = add(w, "bank", [["2026-10-28", "10", "甲", "INV1", ""]])
    w = decide(w, bid, kind)
    original_id = report(w, bid)["rows"][0]["id"]
    w = record_event(w, "allocate", cash=ids(w, "bank")[0], item=ids(w, "receivable")[0], amount_minor=1000, note="核实回款")
    row = report(w, bid)["rows"][0]
    assert row["id"] == original_id
    assert row["own_minor"] == 9000 and row["status"] == "余额已变动需复核" and not row["decision_valid"]


def test_zero_settled_own_is_omitted_unless_partner_lists_reference():
    w, bid = partner_fixture(stated="0")
    w = add(w, "bank", [["2026-10-28", "100", "甲", "INV1", ""]])
    w = record_event(w, "allocate", cash=ids(w, "bank")[0], item=ids(w, "receivable")[0], amount_minor=10000, note="付清")
    row = report(w, bid)["rows"][0]
    assert (row["own_minor"], row["partner_minor"], row["status"]) == (0, 0, "金额一致待确认")
    assert report(decide(w, bid), bid)["rows"][0]["status"] == "已确认"
    w = add(w, "partner_receivable", [["2026-10-25", "5", "甲", "OTHER", ""]])
    other = w.batches[-1].id
    w = record_event(w, "register_partner_statement", batch=other, as_of="2026-10-31", evidence="补充对账单")
    assert [r["reference"] for r in report(w, other)["rows"]] == ["OTHER"]


def test_statement_registration_requires_one_party_current_month_end_and_visible_batch():
    w = add(base(), "partner_receivable", [["2026-10-25", "10", "甲", "X", ""], ["2026-10-25", "20", "乙", "Y", ""]])
    bid = w.batches[-1].id
    with pytest.raises(LocalReconcileError):
        record_event(w, "register_partner_statement", batch=bid, as_of="2026-10-31", evidence="核实")
    w, bid = partner_fixture()
    for day in ("2026-10-30", "2026-11-30", "20261031", "bad"):
        with pytest.raises(LocalReconcileError):
            record_event(w, "register_partner_statement", batch=bid, as_of=day, evidence="核实")
    with pytest.raises(LocalReconcileError):
        record_event(w, "register_partner_statement", batch=w.batches[0].id, as_of="2026-10-31", evidence="核实")
    with pytest.raises(LocalReconcileError):
        record_event(w, "register_partner_statement", batch=bid, as_of="2026-10-31", evidence="")
    changed = record_event(w, "register_partner_statement", batch=bid, as_of="2026-10-31", evidence="更新依据")
    assert changed.state.partner_statements[bid]["evidence"] == "更新依据"


def test_future_source_row_prevents_registering_partial_statement():
    w = add(base(), "partner_receivable", [["2026-10-25", "10", "甲", "X", ""], ["2026-11-01", "20", "甲", "Y", ""]])
    with pytest.raises(LocalReconcileError):
        record_event(w, "register_partner_statement", batch=w.batches[-1].id, as_of="2026-10-31", evidence="核实")


def test_decision_requires_evidence_correct_ids_and_kind():
    w, bid = partner_fixture()
    for kwargs in ({"evidence": ""}, {"own": "missing"}, {"partner": ""}, {"kind": "other"}, {"kind": "explained"}):
        with pytest.raises(LocalReconcileError):
            decide(w, bid, **kwargs)
    row = report(w, bid)["rows"][0]
    with pytest.raises(LocalReconcileError):
        record_event(w, "decide_partner", batch=bid, own=row["partner"], partner=row["own"], kind="confirmed", evidence="核实")


def test_undo_decision_requires_target_and_reason():
    w, bid = partner_fixture()
    w = decide(w, bid)
    target = report(w, bid)["rows"][0]["id"]
    with pytest.raises(LocalReconcileError):
        record_event(w, "undo_partner_decision", target=target, note="")
    w = record_event(w, "undo_partner_decision", target=target, note="重新核实")
    assert report(w, bid)["rows"][0]["status"] == "金额一致待确认"
    with pytest.raises(LocalReconcileError):
        record_event(w, "undo_partner_decision", target=target, note="重复撤销")


def test_month_snapshot_is_deep_copied_and_old_statement_cannot_confirm_next_month():
    w, bid = partner_fixture()
    w = decide(w, bid)
    w = record_event(w, "close_period")
    old = report(w, bid, period="2026-10")
    old["rows"][0]["status"] = "篡改返回值"
    assert report(w, bid, period="2026-10")["rows"][0]["status"] == "已确认"
    w = record_event(w, "advance_period", period="2026-11")
    with pytest.raises(LocalReconcileError, match="期间|月末|截止"):
        report(w, bid)
    with pytest.raises(LocalReconcileError):
        record_event(w, "decide_partner", batch=bid, own=ids(w, "receivable")[0], partner=ids(w, "partner_receivable")[0], kind="confirmed", evidence="旧单")
    with pytest.raises(LocalReconcileError):
        record_event(w, "register_partner_statement", batch=bid, as_of="2026-11-30", evidence="重用旧单")
    assert report(w, bid, period="2026-10")["rows"][0]["status"] == "已确认"


def test_identical_statement_can_be_imported_next_month_with_new_identity(tmp_path):
    from local_reconcile.business.workspace import add_batch
    from local_reconcile.business.storage import save_workspace,load_workspace
    w,bid=partner_fixture()
    old=next(b for b in w.batches if b.id==bid)
    w=record_event(w,'close_period');w=record_event(w,'advance_period',period='2026-11')
    w=add_batch(w,old.role,old.account,old.raw,old.mapping)
    latest=w.batches[-1]
    assert latest.id!=old.id
    w=record_event(w,'register_partner_statement',batch=latest.id,as_of='2026-11-30',evidence='本月余额未变化，重新收到对账单')
    assert report(w,latest.id)['own_total_minor']==10000
    path=tmp_path/'连续月末.lrwork';save_workspace(w,path)
    assert load_workspace(path).state==w.state


@pytest.mark.parametrize('change',['allocate','apply_credit_note'])
def test_decision_does_not_revive_when_balance_returns_after_undo(change):
    w,bid=partner_fixture()
    if change=='allocate':
        w=add(w,'bank',[["2026-10-28",'10','甲','PAY','']])
    else:
        w=add(w,'receivable_credit',[["2026-10-28",'-10','甲','CREDIT','']])
    w=decide(w,bid)
    item=ids(w,'receivable')[0]
    if change=='allocate':
        w=record_event(w,change,cash=ids(w,'bank')[0],item=item,amount_minor=1000,note='回款')
        w=record_event(w,'undo_allocate',target=next(iter(w.state.allocations)),note='更正核销')
    else:
        w=record_event(w,change,credit=ids(w,'receivable_credit')[0],item=item,amount_minor=1000,category='折让',evidence='折让资料')
        w=record_event(w,'undo_credit_note',target=next(iter(w.state.credits)),note='更正折让')
    assert report(w,bid)['rows'][0]['status']=='余额已变动需复核'
    assert report(decide(w,bid),bid)['rows'][0]['status']=='已确认'
