import pytest
from dataclasses import replace
from test_business import base,add,ids
from conftest import raw_table,mapping
from local_reconcile.business.workspace import add_account,add_batch,record_event
from local_reconcile.domain import LocalReconcileError


def lines(w, rows):
    raw=raw_table('ledger',rows)
    raw=replace(raw,headers=('日期','金额','单位','结算行号','摘要','结算批次','类别','订单号'))
    return add_batch(w,'settlement_line','',raw,mapping(declared_account='OPEN-ITEMS'),extra_cols={'settlement':5,'category':6,'order':7})


def fixture(with_order=True):
    w=base()
    if with_order:w=add(w,'settlement_order',[["2026-10-01",'100','平台甲','O1','订单']])
    w=lines(w,[['2026-10-15','100','平台甲','S1','销售','B1','销售','O1'],
               ['2026-10-15','-5','平台甲','R1','退款','B1','退款','O1'],
               ['2026-10-15','-2','平台甲','F1','佣金','B1','佣金',''],
               ['2026-10-15','-1','平台甲','F2','运费','B1','运费','']])
    return add(w,'bank',[["2026-10-16",'92','平台甲','B1','净到账']])


def report(w,**kwargs):
    from local_reconcile.business.net_settlements import net_settlement_reports
    return net_settlement_reports(w,**kwargs)[0]


def confirm(w,**kwargs):
    return record_event(w,'confirm_net_settlement',group=report(w)['id'],banks=ids(w,'bank'),evidence='结算单逐项核实',**kwargs)


def test_net_reconstruction_from_orders_components_and_bank():
    w=fixture();r=report(w)
    assert (r['income_minor'],r['refund_minor'],r['fee_minor'],r['net_minor'])==(10000,500,300,9200)
    assert not r['issues'] and r['bank_minor'] is None
    w=confirm(w);r=report(w)
    assert r['status']=='已确认净到账' and r['review_valid'] and r['difference_minor']==0 and r['bank_minor']==9200
    assert not w.state.allocations and not w.state.matches


def test_missing_order_never_confirms_merely_equal_bank_total():
    w=fixture(False);assert report(w)['issues']
    with pytest.raises(LocalReconcileError):confirm(w)


def test_invalid_sign_or_category_rejected_without_deleting_raw():
    for amount,category,order in [('1','退款','O1'),('-1','销售','O1'),('1','佣金',''),('-1','其他加款',''),('1','未知','')]:
        with pytest.raises(LocalReconcileError):lines(base(),[['2026-10-15',amount,'平台甲','X','','B1',category,order]])


def test_cumulative_order_oversettlement_and_overrefund_require_review():
    w=fixture();w=lines(w,[['2026-10-20','1','平台甲','S2','','B2','销售','O1']])
    assert any('超过' in issue for r in __import__('local_reconcile.business.net_settlements',fromlist=['net_settlement_reports']).net_settlement_reports(w) for issue in r['issues'])
    w=fixture();w=lines(w,[['2026-10-20','-96','平台甲','R2','','B1','退款','O1']])
    assert report(w)['issues']
    with pytest.raises(LocalReconcileError):confirm(w)


def test_exact_bank_sum_no_shared_bank_and_no_cross_account_confirmation():
    w=fixture();w=add(w,'bank',[["2026-10-16",'1','平台甲','OTHER','']])
    with pytest.raises(LocalReconcileError):confirm(w)
    w=add_account(w,'B','第二账户');w=add(w,'bank',[["2026-10-16",'-1','平台甲','OFFSET','']],account='B')
    with pytest.raises(LocalReconcileError):confirm(w)


def test_new_components_with_unchanged_net_require_new_confirmation():
    w=confirm(fixture());w=lines(w,[['2026-10-20','-1','平台甲','F3','','B1','其他扣款',''],['2026-10-20','1','平台甲','A1','','B1','其他加款','']])
    assert report(w)['net_minor']==9200 and not report(w)['review_valid']
    assert '复核' in report(w)['status']
    w=confirm(w);assert report(w)['review_valid']


def test_duplicate_line_and_in_use_exclusion_are_guarded():
    w=confirm(fixture())
    with pytest.raises(LocalReconcileError):record_event(w,'exclude',row=ids(w,'bank')[0],note='已参与结算')
    with pytest.raises(LocalReconcileError):lines(w,[['2026-10-15','100','平台甲','S1','不同文件','B1','销售','O1']])
    w=record_event(w,'undo_net_settlement',target=report(w)['id'],note='更正')
    assert not report(w)['review_valid']


def test_net_history_storage_and_export_are_traceable(tmp_path):
    from local_reconcile.business.storage import save_workspace,load_workspace,export_workspace
    w=confirm(fixture());old=report(w);w=record_event(w,'close_period');w=record_event(w,'advance_period',period='2026-11')
    w=record_event(w,'undo_net_settlement',target=old['id'],note='下期复核')
    assert report(w,period='2026-10')==old
    mutated=report(w,period='2026-10');mutated['status']='changed'
    assert report(w,period='2026-10')['status']=='已确认净到账'
    p=tmp_path/'净结算.lrwork';save_workspace(w,p);assert load_workspace(p).state==w.state
    export_workspace(w,tmp_path/'净结算.xlsx')


def test_extra_order_identifiers_use_same_precision_rules_as_primary_ids():
    w=add(base(),'settlement_order',[["2026-10-01",'100','平台甲',345.0,'']])
    w=lines(w,[['2026-10-15','100','平台甲','S1','','B1','销售',345.0]])
    assert not report(w)['issues']
    with pytest.raises(LocalReconcileError):lines(base(),[['2026-10-15','100','平台甲','S1','','B1','销售',1234567890123456]])


def test_future_order_activity_invalidates_review_when_period_advances():
    w=add(base(),'settlement_order',[["2026-10-01",'100','平台甲','O1','']])
    w=lines(w,[['2026-10-15','50','平台甲','S1','','B1','销售','O1'],['2026-11-15','50','平台甲','S2','','B2','销售','O1']])
    w=add(w,'bank',[["2026-10-16",'50','平台甲','B1','']])
    w=confirm(w);gid=report(w)['id'];assert report(w)['review_valid']
    w=record_event(w,'close_period');w=record_event(w,'advance_period',period='2026-11')
    from local_reconcile.business.net_settlements import net_settlement_reports
    r=next(p for p in net_settlement_reports(w) if p['id']==gid)
    assert r['order_checks'][0]['settled_minor']==10000 and not r['review_valid']
    assert '复核' in r['status']


def test_zero_net_settlement_is_confirmable_without_fabricating_bank_rows():
    w=add(base(),'settlement_order',[["2026-10-01",'100','平台甲','O1','']])
    w=lines(w,[['2026-10-15','100','平台甲','S1','','B1','销售','O1'],['2026-10-16','-100','平台甲','R1','','B1','退款','O1']])
    assert report(w)['bank_minor'] is None and report(w)['net_minor']==0
    w=record_event(w,'confirm_net_settlement',group=report(w)['id'],banks=[],evidence='全额退款抵消，本批次无实际资金往来')
    assert report(w)['review_valid'] and report(w)['bank_minor']==0
    w=record_event(w,'undo_net_settlement',target=report(w)['id'],note='重新核实无资金往来')
    assert report(w)['bank_minor'] is None
