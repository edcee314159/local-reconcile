"""Recognition checks exercise evidence, integer allocation and replay history."""
from copy import deepcopy
import pytest
from conftest import raw_table, mapping
from local_reconcile.domain import LocalReconcileError
from local_reconcile.business.workspace import new_workspace, add_batch, record_event


def business(period="2026-10", amount="100.00", day="2026-10-15", party="甲", reference="B1", invoice="", payment=""):
    w = new_workspace(period)
    raw = raw_table("ledger", [[day, amount, party, reference, "", invoice, payment]],
                    ("日期", "金额", "对方", "编号", "摘要", "开票日", "收付款日"))
    return add_batch(w, "cutoff_business", "", raw, mapping(declared_account="OPEN-ITEMS"),
                     extra_cols={"invoice_day": 5, "payment_day": 6})


def entries(w, rows):
    raw = raw_table("ledger", [list(row) + [f"V{len(w.batches)}-{i}"] for i, row in enumerate(rows)],
                    ("日期", "金额", "对方", "编号", "摘要", "凭证行"))
    return add_batch(w, "cutoff_entry", "", raw, mapping(declared_account="OPEN-ITEMS"), extra_cols={"entry": 5})


def bid(w):
    return next(r.id for r in w.records.values() if r.role == "cutoff_business")


def rule(w, method="once", start="2026-10-15", end="2026-10-15", evidence="财务核实验收及归属依据"):
    return record_event(w, "register_cutoff_rule", business=bid(w), method=method, start=start, end=end, evidence=evidence)


def report(w, period=None):
    from local_reconcile.business.cutoff import cutoff_report
    return cutoff_report(w, period)


def row(w):
    return next(r for r in report(w)["rows"] if r["business"])


def advance(w, period):
    return record_event(record_event(w, "close_period"), "advance_period", period=period)


def explain(w):
    return record_event(w, "explain_cutoff", business=bid(w), evidence="差额核实说明")


def test_missing_rule_never_infers_zero_or_posting_from_invoice_payment():
    w = business(invoice="2026-10-15", payment="2026-10-15")
    r = row(w)
    assert r["expected_minor"] is None and r["delta_minor"] is None and r["prior_delta_minor"] is None
    assert r["actual_minor"] == 0 and r["status"] == "归属规则待确认"


def test_once_matches_signed_entries_exact_party_reference_and_omits_future():
    w = rule(business())
    w = entries(w, [["2026-10-20", "120", "甲", "B1", ""], ["2026-10-21", "-20", "甲", "B1", ""],
                    ["2026-11-01", "7", "甲", "B1", ""], ["2026-10-20", "100", "乙", "B1", ""]])
    r = row(w)
    assert (r["expected_minor"], r["actual_minor"], r["delta_minor"], r["status"]) == (10000, 10000, 0, "核对一致")
    assert len(r["entries"]) == 2
    unmatched = next(p for p in report(w)["rows"] if not p["business"])
    assert unmatched["party"] == "乙" and unmatched["expected_minor"] is None
    assert unmatched["status"] == "记账记录未关联业务"


def test_monthly_allocates_remainder_to_earliest_inclusive_months():
    w = rule(business("2026-01", "0.10", "2026-01-12"), "monthly", "2026-01-12", "2026-03-20")
    assert row(w)["expected_minor"] == 4
    w = advance(w, "2026-02")
    assert row(w)["expected_minor"] == 3 and row(w)["prior_delta_minor"] == -4
    w = advance(w, "2026-03")
    assert row(w)["expected_minor"] == 3 and row(w)["prior_delta_minor"] == -7
    assert sum(report(w, p)["rows"][0]["expected_minor"] for p in ("2026-01", "2026-02")) + row(w)["expected_minor"] == 10


def test_daily_cumulative_integer_allocation_conserves_leap_year_cents():
    w = rule(business("2024-01", "0.61", "2024-01-31"), "daily", "2024-01-31", "2024-03-01")
    assert row(w)["expected_minor"] == 1
    w = advance(w, "2024-02")
    assert row(w)["expected_minor"] == 58
    w = advance(w, "2024-03")
    assert row(w)["expected_minor"] == 2 and row(w)["prior_delta_minor"] == -59


def test_daily_single_day_at_maximum_date_and_large_integer_amount():
    w = rule(business("9999-12", "90071992547409.93", "9999-12-31"), "daily", "9999-12-31", "9999-12-31")
    assert row(w)["expected_minor"] == 9007199254740993


def test_future_rule_exposes_over_recognition_and_prior_differences():
    w = rule(business(), "monthly", "2026-11-01", "2026-12-31")
    w = entries(w, [["2026-09-01", "10", "甲", "B1", ""], ["2026-10-02", "20", "甲", "B1", ""]])
    r = row(w)
    assert (r["expected_minor"], r["actual_minor"], r["delta_minor"], r["prior_delta_minor"]) == (0, 2000, 2000, 1000)
    assert "本期多记" in r["flags"] and "以前期间差异" in r["flags"]


def test_negative_reversal_stays_signed_and_flags_negative_cumulative():
    w = entries(rule(business()), [["2026-10-20", "-20", "甲", "B1", ""]])
    r = row(w)
    assert r["actual_minor"] == -2000 and r["delta_minor"] == -12000
    assert "本期少记" in r["flags"] and "累计记账为负" in r["flags"]


def test_invoice_and_payment_crossing_are_warnings_even_when_amount_equal():
    w = entries(rule(business(invoice="2026-09-30", payment="2026-11-01")), [["2026-10-15", "100", "甲", "B1", ""]])
    r = row(w)
    assert r["delta_minor"] == 0 and r["status"] != "核对一致"
    assert {"开票跨期", "收付款跨期"} <= set(r["flags"])
    assert r["invoice_day"] == "2026-09-30" and r["payment_day"] == "2026-11-01"


@pytest.mark.parametrize("method,start,end", [
    ("unknown", "2026-10-15", "2026-10-15"),
    ("once", "2026-10-14", "2026-10-14"),
    ("daily", "2026-10-16", "2026-10-15"),
    ("monthly", "1899-12-31", "2026-10-15"),
    ("monthly", "1900-01-01", "2000-01-01"),
])
def test_rejects_invalid_or_excessive_recognition_rule(method, start, end):
    with pytest.raises(LocalReconcileError):
        rule(business(), method, start, end)


def test_rule_and_explanation_require_evidence_and_active_business():
    w = business()
    with pytest.raises(LocalReconcileError): rule(w, evidence=" ")
    with pytest.raises(LocalReconcileError): explain(w)
    with pytest.raises(LocalReconcileError): record_event(w, "register_cutoff_rule", business="missing", method="once", start="2026-10-15", end="2026-10-15", evidence="依据")
    w = rule(w)
    with pytest.raises(LocalReconcileError): record_event(w, "explain_cutoff", business=bid(w), evidence=" ")


def test_explanation_preserves_discrepancy_and_rule_revision_requires_review():
    w = explain(rule(business()))
    assert row(w)["explanation_valid"] and row(w)["delta_minor"] == -10000
    assert row(w)["status"] == "差异已说明仍待复核"
    w = rule(w, evidence="修订归属依据")
    assert not row(w)["explanation_valid"] and row(w)["status"] == "依据或金额已变化需复核"
    assert row(explain(w))["explanation_valid"]


def test_exclusion_restore_does_not_resurrect_old_explanation():
    w = explain(entries(rule(business()), [["2026-10-20", "90", "甲", "B1", ""]]))
    entry = next(r.id for r in w.records.values() if r.role == "cutoff_entry")
    w = record_event(w, "exclude", row=entry, note="排除复核")
    assert not row(w)["explanation_valid"] and row(w)["actual_minor"] == 0
    w = record_event(w, "undo_exclude", row=entry, note="恢复来源")
    assert not row(w)["explanation_valid"] and row(w)["actual_minor"] == 9000
    assert row(explain(w))["explanation_valid"]


def test_late_entry_import_changes_current_prior_difference_without_mutating_history():
    w = explain(rule(business()))
    saved = deepcopy(report(w))
    w = advance(w, "2026-11")
    w = entries(w, [["2026-10-20", "100", "甲", "B1", ""]])
    assert report(w, "2026-10") == saved
    r = row(w)
    assert r["prior_delta_minor"] == 0 and not r["explanation_valid"]
    historical = report(w, "2026-10")
    historical["rows"].clear()
    assert report(w, "2026-10") == saved


def test_late_business_import_creates_prior_omission_in_current_only():
    w = advance(new_workspace("2026-10"), "2026-11")
    source = business()
    raw = source.batches[0].raw
    w = add_batch(w, "cutoff_business", "", raw, mapping(declared_account="OPEN-ITEMS"), extra_cols={"invoice_day": 5, "payment_day": 6})
    w = rule(w)
    assert row(w)["prior_delta_minor"] == -10000 and report(w, "2026-10")["rows"] == []


def test_undo_explanation_required_before_rule_and_source_remains_protected():
    w = explain(rule(business()))
    with pytest.raises(LocalReconcileError): record_event(w, "undo_cutoff_rule", target=bid(w), note="撤销")
    with pytest.raises(LocalReconcileError): record_event(w, "exclude", row=bid(w), note="排除")
    w = record_event(w, "undo_cutoff_explanation", target=bid(w), note="撤销说明")
    w = record_event(w, "undo_cutoff_rule", target=bid(w), note="撤销规则")
    assert row(w)["expected_minor"] is None and not row(w)["explanation"]


def test_report_rejects_unsaved_period_and_missing_legacy_snapshot():
    w = business()
    with pytest.raises(LocalReconcileError): report(w, "2026-09")
    s = w.state
    s.closings["2026-09"] = {}
    from local_reconcile.business.cutoff import cutoff_report
    with pytest.raises(LocalReconcileError): cutoff_report(w, "2026-09", state=s)

