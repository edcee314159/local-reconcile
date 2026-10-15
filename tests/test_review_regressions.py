from dataclasses import replace
import pytest
from conftest import raw_table, mapping, dataset
from local_reconcile.domain import MatchConfig, LocalReconcileError, ProjectSnapshot, ReviewEvent
from local_reconcile.normalize import normalize
from local_reconcile.matching import reconcile
from local_reconcile.review import apply_review
from test_ui_flow import app


@pytest.mark.parametrize("empty", ["", None])
def test_dual_columns_both_missing_block_reconciliation(empty):
    m = mapping(amount_col=None, income_col=1, expense_col=2, party_col=3,
                reference_col=4, summary_col=None, direction="income_expense")
    headers = ("日期", "收入", "支出", "对方", "编号")
    b = normalize(raw_table("bank", [["2026-10-15", empty, empty, "甲", "A"]], headers), m)
    l = normalize(raw_table("ledger", [["2026-10-15", empty, empty, "甲", "A"]], headers), m)
    assert not b.transactions
    assert any(i.severity == "error" and i.row_ids == ("bank-0",) for i in b.issues)
    with pytest.raises(LocalReconcileError):
        reconcile(b, l, MatchConfig())


def test_dual_columns_explicit_zero_remains_a_zero_record():
    m = mapping(amount_col=None, income_col=1, expense_col=2, party_col=None,
                reference_col=None, summary_col=None, direction="income_expense")
    b = normalize(raw_table("bank", [["2026-10-15", "0", ""]], ("日期", "收入", "支出")), m)
    assert b.transactions[0].amount_minor == 0
    assert not any(i.severity == "error" for i in b.issues)


def test_manual_pair_can_be_selected_and_undone_in_window(app):
    from local_reconcile.ui.main_window import MainWindow
    b = dataset("bank", [["2026-10-15", "10", "甲", "A", ""]])
    l = dataset("ledger", [["2026-10-15", "10", "乙", "B", ""]])
    config = MatchConfig()
    s = ProjectSnapshot(1, b, l, config, reconcile(b, l, config))
    assert not s.result.candidates
    s = apply_review(s, ReviewEvent(1, "confirm", "bank-0", "ledger-0", "已核实业务资料"))
    w = MainWindow()
    try:
        w.snapshot = s
        w.results_page.render(s)
        w.results_page.filter.setCurrentText("已确认")
        assert w.results_page.table.model().rowCount() == 1
        w.results_page.table.selectRow(0)
        assert "银行流水" in w.results_page.detail.toPlainText()
        w.review_selection("undo")
        assert not w.snapshot.review.pairs
        assert w.snapshot.review.events[-1].kind == "undo"
    finally:
        w.dirty = False
        w.close()


def test_wildcard_party_component_is_capped_across_distinct_parties():
    b = dataset("bank", [["2026-10-15", "10", f"客户{i}", "", ""] for i in range(1000)])
    l = dataset("ledger", [["2026-10-15", "10", "", "", ""] for _ in range(100)])
    r = reconcile(b, l, MatchConfig())
    assert not r.candidates
    groups = [g for g in r.groups if g.truncated]
    assert len(groups) == 1
    assert set(groups[0].bank_ids) == {t.id for t in b.transactions}
    assert set(groups[0].ledger_ids) == {t.id for t in l.transactions}


def test_distinct_parties_without_wildcards_stay_independent():
    rows = [["2026-10-15", "10", f"客户{i}", "", ""] for i in range(200)]
    r = reconcile(dataset("bank", rows), dataset("ledger", rows), MatchConfig())
    assert len(r.candidates) == 200
    assert not r.groups
