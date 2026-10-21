from test_ui_flow import app
from test_settlements import cashbook
from local_reconcile.ui.business_window import BusinessWindow
from local_reconcile.business.workspace import record_event
from local_reconcile.business.operations import open_items
from local_reconcile.business.settlements import advance_rows


def test_refund_controls_restore_balance(app):
    w=BusinessWindow()
    try:
        data,o,c,i=cashbook();data=record_event(data,'allocate',cash=o,item=i,amount_minor=10000,note='')
        a=next(iter(data.state.allocations));w.set_workspace(data)
        assert w.tabs.count()==12
        w.refund_original.setCurrentIndex(w.refund_original.findData(o))
        w.refund_cash.setCurrentIndex(w.refund_cash.findData(c))
        w.refund_target.setCurrentIndex(w.refund_target.findData('allocation:'+a))
        w.refund_amount.setText('30');w.refund_evidence.setText('银行回单')
        w.refund_selected()
        assert open_items(w.workspace)[0]['remaining_minor']==3000
        assert w.refund_table.model().rowCount()==1
    finally:w.dirty=False;w.close()


def test_advance_controls_register_and_allocate(app):
    w=BusinessWindow()
    try:
        data,o,c,i=cashbook();w.set_workspace(data)
        w.advance_cash.setCurrentIndex(w.advance_cash.findData(o))
        w.advance_amount.setText('100');w.advance_evidence.setText('预收款协议');w.register_advance_selected()
        a=next(iter(w.workspace.state.advances));w.advance_combo.setCurrentIndex(w.advance_combo.findData(a))
        w.advance_item.setCurrentIndex(w.advance_item.findData(i))
        w.advance_allocation_amount.setText('60');w.advance_note.setText('核实');w.allocate_advance_selected()
        assert advance_rows(w.workspace)[0]['remaining_minor']==4000
        assert w.advance_table.model().rowCount()==1
    finally:w.dirty=False;w.close()


def test_expansion_bundled_smoke(app,tmp_path):
    from local_reconcile.business.smoke import run_business_smoke
    result=run_business_smoke(tmp_path)
    assert result['many_to_many_relations']==1
    assert result['refunds']==2
    assert result['advance_remaining_minor']==1000
    assert result['reopened_receivable_minor']==3000
