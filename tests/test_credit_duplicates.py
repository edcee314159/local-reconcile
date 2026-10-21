import pytest
from test_business import base,add,ids
from test_settlements import cashbook,refund
from local_reconcile.business.workspace import record_event
from local_reconcile.business.operations import open_items,cash_remaining
from local_reconcile.business.storage import save_workspace,load_workspace,export_workspace
from local_reconcile.domain import LocalReconcileError


@pytest.mark.parametrize('role,credit_role',[('receivable','receivable_credit'),('payable','payable_credit')])
def test_credit_note_reduces_debt_and_caps_cash_allocation(role,credit_role):
    w=add(base(),role,[["2026-10-01",'100','甲','I1','']])
    w=add(w,credit_role,[["2026-10-10",'-30','甲','C1','退货']])
    credit=ids(w,credit_role)[0];item=ids(w,role)[0]
    w=record_event(w,'apply_credit_note',credit=credit,item=item,amount_minor=3000,category='退货',evidence='退货及红字资料')
    row=open_items(w)[0];assert row['remaining_minor']==7000 and row['credited_minor']==3000 and row['allocated_minor']==0
    w=add(w,'bank',[["2026-10-15",'100' if role=='receivable' else '-100','甲','PAY','']])
    cash=ids(w,'bank')[0]
    with pytest.raises(LocalReconcileError):record_event(w,'allocate',cash=cash,item=item,amount_minor=8000,note='')
    w=record_event(w,'allocate',cash=cash,item=item,amount_minor=7000,note='');assert open_items(w)[0]['remaining_minor']==0
    with pytest.raises(LocalReconcileError):record_event(w,'apply_credit_note',credit=credit,item=item,amount_minor=1,category='折让',evidence='不可重复')


def test_paid_invoice_refund_then_credit_and_safe_undo():
    w,o,c,i=cashbook();w=record_event(w,'allocate',cash=o,item=i,amount_minor=10000,note='')
    w=add(w,'receivable_credit',[["2026-10-12",'30','甲','C1','']]);credit=ids(w,'receivable_credit')[0]
    with pytest.raises(LocalReconcileError):record_event(w,'apply_credit_note',credit=credit,item=i,amount_minor=3000,category='红字抵减',evidence='已付未退')
    w=refund(w,o,c,allocation=next(iter(w.state.allocations)))
    w=record_event(w,'apply_credit_note',credit=credit,item=i,amount_minor=3000,category='红字抵减',evidence='退货红字单')
    assert open_items(w)[0]['remaining_minor']==0
    with pytest.raises(LocalReconcileError):record_event(w,'undo_refund',target=next(iter(w.state.refunds)),note='不可超额')
    w=record_event(w,'undo_credit_note',target=next(iter(w.state.credits)),note='更正');assert open_items(w)[0]['remaining_minor']==3000


def test_credit_roundtrip_snapshot_and_source_preserved(tmp_path):
    from local_reconcile.business.credits import credit_rows
    w=add(base(),'receivable',[["2026-10-01",'100','甲','I1','']]);w=add(w,'receivable_credit',[["2026-10-10",'-30','甲','C1','']])
    credit=ids(w,'receivable_credit')[0];item=ids(w,'receivable')[0]
    w=record_event(w,'apply_credit_note',credit=credit,item=item,amount_minor=1000,category='折让',evidence='折让协议')
    assert credit_rows(w)[0]['remaining_minor']==2000
    with pytest.raises(LocalReconcileError):record_event(w,'exclude',row=credit,note='已使用')
    w=record_event(w,'close_period');w=record_event(w,'advance_period',period='2026-11')
    w=record_event(w,'undo_credit_note',target=next(iter(w.state.credits)),note='次月更正')
    assert w.state.closings['2026-10']['open_items'][item]==9000
    path=tmp_path/'红字.lrwork';save_workspace(w,path);restored=load_workspace(path)
    assert restored.records==w.records and open_items(restored)[0]['remaining_minor']==10000
    export_workspace(restored,tmp_path/'报告.xlsx')


def duplicate_fixture():
    w=add(base(),'bank',[["2026-10-15",'100','甲','PAY','原导出']])
    return add(w,'bank',[["2026-10-15",'100','甲','PAY','再次导出']])


def test_cross_batch_duplicates_block_use_until_reviewed():
    from local_reconcile.business.duplicates import duplicate_groups
    w=duplicate_fixture();groups=duplicate_groups(w);assert len(groups)==1 and groups[0]['status']=='待复核'
    w=add(w,'receivable',[["2026-10-01",'300','甲','I1','']]);cash=ids(w,'bank')[0];item=ids(w,'receivable')[0]
    with pytest.raises(LocalReconcileError):record_event(w,'allocate',cash=cash,item=item,amount_minor=10000,note='')
    w=record_event(w,'review_duplicate',group=duplicate_groups(w)[0]['id'],evidence='已查回单为两笔独立业务')
    w=record_event(w,'allocate',cash=cash,item=item,amount_minor=10000,note='')
    assert open_items(w)[0]['remaining_minor']==20000


def test_excluding_duplicate_resolves_group_and_new_batch_requires_new_review():
    from local_reconcile.business.duplicates import duplicate_groups
    w=duplicate_fixture();group=duplicate_groups(w)[0]
    accepted=record_event(w,'review_duplicate',group=group['id'],evidence='逐笔核实为独立业务')
    accepted=add(accepted,'bank',[["2026-10-15",'100','甲','PAY','第三次导出']])
    assert duplicate_groups(accepted)[0]['status']=='待复核'
    w=record_event(w,'exclude',row=ids(w,'bank')[1],note='确认为重复导出')
    assert not duplicate_groups(w) and len(w.records)==2


def test_distinct_nonempty_references_are_not_flagged():
    from local_reconcile.business.duplicates import duplicate_groups
    w=add(base(),'bank',[["2026-10-15",'100','甲','R1','']]);w=add(w,'bank',[["2026-10-15",'100','甲','R2','']])
    assert not duplicate_groups(w)
    w=add(w,'bank',[["2026-10-15",'100','甲','','缺编号']])
    assert duplicate_groups(w)


@pytest.mark.parametrize('field,value',[('amount_minor',0),('amount_minor',-1),('amount_minor',True),('amount_minor',3001),('evidence',''),('category','任意')])
def test_credit_rejects_invalid_or_excessive_adjustment(field,value):
    w=add(base(),'receivable',[["2026-10-01",'100','甲','I1','']])
    w=add(w,'receivable_credit',[["2026-10-10",'-30','甲','C1','']])
    data=dict(credit=ids(w,'receivable_credit')[0],item=ids(w,'receivable')[0],amount_minor=3000,category='退货',evidence='资料')
    data[field]=value
    with pytest.raises(LocalReconcileError):record_event(w,'apply_credit_note',**data)


def test_duplicate_advance_cannot_be_allocated_after_new_suspicious_batch():
    w=add(base(),'bank',[["2026-10-01",'100','甲','P1','原预收']]);cash=ids(w,'bank')[0]
    w=record_event(w,'register_advance',cash=cash,amount_minor=10000,evidence='原预收')
    advance=next(iter(w.state.advances))
    w=add(w,'receivable',[["2026-10-10",'100','甲','I1','']])
    w=add(w,'bank',[["2026-10-01",'100','甲','P1','再次导出']])
    with pytest.raises(LocalReconcileError):record_event(w,'allocate_advance',advance=advance,item=ids(w,'receivable')[0],amount_minor=1000,note='')
