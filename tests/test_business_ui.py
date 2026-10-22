from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_ui_flow import app, wait_until
from local_reconcile.ui.business_window import BusinessWindow
from local_reconcile.business.demo import make_demo
from local_reconcile.business.workspace import record_event
from local_reconcile.business.storage import load_workspace
from local_reconcile.business.smoke import run_business_smoke


def test_five_business_tabs_and_real_workflow(app,tmp_path):
    w=BusinessWindow();w.show()
    try:
        w.set_workspace(make_demo())
        assert w.tabs.count()==14
        w.analyze();wait_until(app,lambda:not w.busy)
        assert w.analysis and w.analysis.candidates
        w.match_table.selectRow(0)
        QTest.mouseClick(w.confirm_button,Qt.LeftButton)
        assert len(w.workspace.state.matches)==1
        w.confirmed_table.selectRow(0);w.undo_match()
        assert not w.workspace.state.matches
        p=tmp_path/"新业务.lrwork";w.save_to(p);wait_until(app,lambda:not w.busy)
        assert p.exists() and load_workspace(p).records==w.workspace.records
        out=tmp_path/"核算报告.xlsx";w.export_to(out);wait_until(app,lambda:not w.busy)
        assert out.exists()
        w.load_from(p);wait_until(app,lambda:not w.busy)
        assert len(w.workspace.accounts)==2
    finally:
        w.dirty=False;w.close()


def test_business_smoke_all_five_features(app,tmp_path):
    result=run_business_smoke(tmp_path)
    assert result["combination_relations"]>=1
    assert result["difference_explanations"]==1
    assert result["remaining_receivable_minor"]==700000
    assert result["internal_transfers"]==1
    assert result["closed_periods"]==1
    assert (tmp_path/"business-report.xlsx").exists()


def test_business_main_entry_and_all_business_actions(app):
    from local_reconcile.ui.main_window import MainWindow
    from local_reconcile.business.operations import open_items
    main=MainWindow();QTest.mouseClick(main.business_button,Qt.LeftButton)
    w=main.business_window
    try:
        assert w is not None and w.tabs.count()==14
        w.set_workspace(make_demo())
        records=list(w.workspace.records.values())
        bank=next(r for r in records if r.role=="bank" and r.reference=="SET-02")
        ledger=next(r for r in records if r.role=="ledger" and r.reference=="SET-02")
        w.diff_bank.setCurrentIndex(w.diff_bank.findData(bank.id))
        w.diff_ledger.setCurrentIndex(w.diff_ledger.findData(ledger.id))
        w.diff_evidence.setText("虚构结算资料");w.explain_selected()
        assert len(w.workspace.state.explanations)==1
        cash=next(r for r in records if r.role=="bank" and r.reference=="PAY-03")
        item=next(r for r in records if r.role=="receivable")
        w.cash_combo.setCurrentIndex(w.cash_combo.findData(cash.id))
        w.item_combo.setCurrentIndex(w.item_combo.findData(item.id))
        w.allocation_amount.setText("3000");w.allocation_note.setText("已核实");w.allocate_selected()
        assert next(x for x in open_items(w.workspace) if x["record"].id==item.id)["remaining_minor"]==700000
        out=next(r for r in records if r.role=="bank" and r.reference=="TR-01" and r.amount_minor<0)
        inc=next(r for r in records if r.role=="bank" and r.reference=="TR-01" and r.amount_minor>0)
        w.outgoing_combo.setCurrentIndex(w.outgoing_combo.findData(out.id))
        w.incoming_combo.setCurrentIndex(w.incoming_combo.findData(inc.id))
        w.transfer_evidence.setText("本企业双账户核实");w.transfer_selected()
        assert len(w.workspace.state.transfers)==1
        w.apply("close_period");w.apply("advance_period",period="2026-11")
        assert "2026-10" in w.workspace.state.closings
    finally:
        w.dirty=False;w.close();main.dirty=False;main.close()
