from test_ui_flow import app
from test_reporting import fixture,aging_fixture
from local_reconcile.ui.business_window import BusinessWindow


def test_balance_adjustment_page_and_manual_classification(app):
    w=BusinessWindow()
    try:
        w.set_workspace(fixture());assert w.tabs.count()==9
        w.bank_closing.setText('1000');w.ledger_closing.setText('960');w.balance_evidence.setText('期末余额资料');w.save_balances_selected()
        rows=list(w.workspace.records)
        for rid in rows:
            w.adjustment_row.setCurrentIndex(w.adjustment_row.findData(rid));w.adjustment_evidence.setText('人工核实回单');w.classify_selected()
        assert '调节后相符' in w.balance_status.text()
        assert w.adjustment_table.model().rowCount()==4
    finally:w.dirty=False;w.close()


def test_aging_page_filters_and_history(app):
    w=BusinessWindow()
    try:
        w.set_workspace(aging_fixture());assert w.aging_detail_table.model().rowCount()==8
        w.aging_overdue.setChecked(True);assert w.aging_detail_table.model().rowCount()==4
        w.aging_overdue.setChecked(False);w.aging_role.setCurrentIndex(w.aging_role.findData('payable'))
        assert w.aging_detail_table.model().rowCount()==1
        w.apply('close_period');w.apply('advance_period',period='2026-11')
        w.aging_period.setCurrentIndex(w.aging_period.findData('2026-10'))
        assert w.aging_detail_table.model().rowCount()==1
    finally:w.dirty=False;w.close()


def test_reporting_executable_smoke(app,tmp_path):
    from local_reconcile.business.smoke import run_business_smoke
    result=run_business_smoke(tmp_path)
    assert result['bank_adjustment_difference_minor']==0
    assert result['aging_receivable_minor']==10000
    assert result['aging_overdue_minor']==10000
    assert result['historical_adjustment_preserved'] is True
