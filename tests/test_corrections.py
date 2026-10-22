from copy import deepcopy
from dataclasses import replace
from concurrent.futures import CancelledError
import pytest
from test_business import base,add,ids
from test_settlements import cashbook,refund
from local_reconcile.business.workspace import record_event,add_account
from local_reconcile.business.operations import open_items
from local_reconcile.domain import LocalReconcileError


def fixture():
    w=add(base(),'bank',[["2026-10-10",'50','甲','PAY','']])
    w=add(w,'receivable',[["2026-10-01",'100','甲','I1',''],["2026-10-01",'100','甲','I2','']])
    first,second=ids(w,'receivable')
    w=record_event(w,'allocate',cash=ids(w,'bank')[0],item=first,amount_minor=4000,note='原核销')
    target=next(iter(w.state.allocations))
    ops=[{'kind':'undo_allocate','data':{'target':target,'note':'原单据选错'}},{'kind':'allocate','data':{'cash':ids(w,'bank')[0],'item':second,'amount_minor':4000,'note':'改核销另一单'}}]
    return w,first,second,ops


def test_preview_shows_changes_without_mutating_original():
    from local_reconcile.business.corrections import preview_correction
    w,first,second,ops=fixture();before=deepcopy(w.state);events=deepcopy(w.events)
    p=preview_correction(w,ops,'核销对象更正')
    assert p['ok'] and not p['error'] and p['changes']
    assert w.state==before and w.events==events and len(w.state.allocations)==1
    assert any(c['key']==first and c['before']=='60.00' and c['after']=='100.00' for c in p['changes'])
    assert any(c['key']==second and c['after']=='60.00' for c in p['changes'])


def test_apply_resimulates_atomically_and_records_audit(tmp_path):
    from local_reconcile.business.corrections import preview_correction,apply_correction
    from local_reconcile.business.storage import save_workspace,load_workspace
    w,first,second,ops=fixture();p=preview_correction(w,ops,'核销对象更正')
    after=apply_correction(w,p,'核销对象更正')
    assert [r['remaining_minor'] for r in open_items(w)]==[6000,10000]
    assert [r['remaining_minor'] for r in open_items(after)]==[10000,6000]
    assert len(after.state.corrections)==1 and len(after.events)==len(w.events)+3
    assert next(iter(after.state.corrections.values()))['reason']=='核销对象更正'
    path=tmp_path/'更正.lrwork';save_workspace(after,path);assert load_workspace(path).state==after.state


def test_failure_mid_plan_never_commits_partial_undo():
    from local_reconcile.business.corrections import preview_correction,apply_correction
    w,first,second,ops=fixture();ops[1]['data']['amount_minor']=20000
    p=preview_correction(w,ops,'超额方案应失败')
    assert not p['ok'] and p['error'] and not p['changes']
    assert len(w.state.allocations)==1
    with pytest.raises(LocalReconcileError):apply_correction(w,p,'超额方案应失败')


def test_refund_dependency_is_reported_and_not_automatically_removed():
    from local_reconcile.business.corrections import preview_correction
    w,o,c,i=cashbook();w=record_event(w,'allocate',cash=o,item=i,amount_minor=10000,note='')
    target=next(iter(w.state.allocations));w=refund(w,o,c,allocation=target)
    p=preview_correction(w,[{'kind':'undo_allocate','data':{'target':target,'note':'更正'}}],'先检查关联')
    assert not p['ok'] and any(b['target'] in w.state.refunds for b in p['blockers'])
    assert len(w.state.refunds)==1 and len(w.state.allocations)==1


def test_stale_base_same_event_count_is_rejected():
    from local_reconcile.business.corrections import preview_correction,apply_correction
    w,_,_,ops=fixture();p=preview_correction(w,ops,'更正')
    changed=add_account(w,'B','新登记账户')
    assert len(changed.events)==len(w.events)
    with pytest.raises(LocalReconcileError):apply_correction(changed,p,'更正')


def test_mutated_operation_and_changed_reason_require_new_preview():
    from local_reconcile.business.corrections import preview_correction,apply_correction
    w,_,_,ops=fixture();p=preview_correction(w,ops,'更正')
    p['operations'][1]['data']['amount_minor']=3000
    with pytest.raises(LocalReconcileError):apply_correction(w,p,'更正')
    p=preview_correction(w,ops,'更正')
    with pytest.raises(LocalReconcileError):apply_correction(w,p,'改了依据')


@pytest.mark.parametrize('kind',['import_batch','close_period','advance_period','record_correction','change_raw_data'])
def test_structural_or_history_changes_not_allowed(kind):
    from local_reconcile.business.corrections import preview_correction
    w,_,_,_=fixture();p=preview_correction(w,[{'kind':kind,'data':{}}],'不允许')
    assert not p['ok'] and not p['changes']


def test_cancelled_preview_raises_without_changes():
    from local_reconcile.business.corrections import preview_correction
    w,_,_,ops=fixture()
    with pytest.raises(CancelledError):preview_correction(w,ops,'取消',cancelled=lambda:True)
    assert len(w.state.allocations)==1


def test_previous_month_snapshots_unchanged_by_current_correction():
    from local_reconcile.business.corrections import preview_correction,apply_correction
    w,first,second,ops=fixture();w=record_event(w,'close_period');old=deepcopy(w.state.closings)
    w=record_event(w,'advance_period',period='2026-11');p=preview_correction(w,ops,'下月纠正原核销')
    assert p['ok']
    after=apply_correction(w,p,'下月纠正原核销')
    assert after.state.closings==old and after.state.closings['2026-10']['open_items'][first]==6000


def test_audited_correction_allows_later_account_and_source_import(tmp_path):
    from local_reconcile.business.corrections import preview_correction,apply_correction
    from local_reconcile.business.storage import save_workspace,load_workspace
    w,_,_,ops=fixture();w=apply_correction(w,preview_correction(w,ops,'更正'),'更正')
    w=add_account(w,'B','后登记账户')
    w=add(w,'receivable',[["2026-10-20",'20','乙','LATER','后补单据']])
    assert len(w.state.corrections)==1
    path=tmp_path/'later.lrwork';save_workspace(w,path);assert load_workspace(path).state==w.state


def test_distinct_orphan_postings_keep_separate_preview_metrics():
    from conftest import raw_table,mapping
    from local_reconcile.business.workspace import new_workspace,add_batch
    from local_reconcile.business.cutoff import cutoff_report
    from local_reconcile.business.corrections import preview_correction
    raw=raw_table('ledger', [['2026-10-01','100','A','ORPHAN-A','','E-A'],['2026-10-01','200','B','ORPHAN-B','','E-B']], ('date','amount','party','ref','summary','entry'))
    w=add_batch(new_workspace('2026-10'),'cutoff_entry','',raw,mapping(declared_account='OPEN-ITEMS'),extra_cols={'entry':5})
    reports=cutoff_report(w)['rows']
    assert [p['actual_minor'] for p in reports]==[10000,20000]
    target=reports[0]['entries'][0]
    preview=preview_correction(w,[{'kind':'exclude','data':{'row':target,'note':'remove erroneous posting'}}],'correct source inclusion')
    assert preview['ok']
    assert preview['changes'], preview


def test_old_partner_statement_does_not_block_current_month_corrections():
    from local_reconcile.business.corrections import preview_correction
    w,_,_,ops=fixture()
    w=add(w,'partner_receivable',[["2026-10-01",'60','甲','I1','']])
    batch=w.batches[-1].id
    w=record_event(w,'register_partner_statement',batch=batch,as_of='2026-10-31',evidence='十月客户对账')
    w=record_event(w,'close_period');w=record_event(w,'advance_period',period='2026-11')
    p=preview_correction(w,ops,'十一月纠正核销')
    assert p['ok'],p['error']
