import threading
from dataclasses import replace
from unittest.mock import patch
import pytest
from PySide6.QtTest import QTest
from test_ui_flow import app,wait_until
from test_business import base,add
from local_reconcile.ui.business_window import BusinessWindow
from local_reconcile.business.storage import save_workspace,load_workspace
from local_reconcile.business.matching import suggest_matches


def test_cancelled_old_save_cannot_overwrite_new_save(app,tmp_path):
    import local_reconcile.business.storage as storage
    w=BusinessWindow();w.set_workspace(base());path=tmp_path/'保存.lrwork';save_workspace(w.workspace,path);w.path=path;w.dirty=True
    entered=threading.Event();release=threading.Event();second_started=threading.Event();original=storage.os.replace;calls=[]
    def controlled_replace(src,dst):
        calls.append(str(src))
        if len(calls)==1:
            entered.set()
            if not release.wait(8):raise RuntimeError('save probe timed out')
        else:second_started.set()
        return original(src,dst)
    try:
        with patch.object(storage.os,'replace',side_effect=controlled_replace):
            w.save_to(path);wait_until(app,entered.is_set);w.cancel()
            w.apply('set_closing_balances',account='A',bank_minor=10000,ledger_minor=10000,evidence='第二次保存的新余额')
            w.save_to(path)
            # The newer save must wait for the canceled commit already in flight.
            assert not second_started.wait(.15)
            release.set();wait_until(app,lambda:not w.busy and not w.runner.jobs)
            assert load_workspace(path).state.closing_balances==w.workspace.state.closing_balances
            assert not w.dirty
    finally:release.set();w.dirty=False;w.close()


def test_same_party_distinct_references_use_linear_checks(monkeypatch):
    import local_reconcile.business.matching as engine
    rows=[["2026-10-15",'10','同一客户',f'R{i}',''] for i in range(400)]
    w=add(base(),'bank',rows);w=add(w,'ledger',rows)
    original=engine.relation_basis;calls=[]
    def measured(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(engine,'relation_basis',measured)
    result=suggest_matches(w)
    assert len(result.candidates)==400 and not result.ranges
    assert len(calls)<=2400


def wide_pool(monkeypatch):
    import local_reconcile.business.matching as engine
    w=add(base(),'bank',[["2026-10-15",'1000','客户','X','']])
    w=add(w,'ledger',[["2026-10-15",'1','客户','',''] for _ in range(400)])
    records={}
    for r in w.records.values():
        r=replace(r,id=('0-' if r.role=='bank' else '1-')+r.id);records[r.id]=r
    monkeypatch.setattr(engine,'active_records',lambda _:records)
    return w


def test_candidate_pool_scans_obey_project_budget(monkeypatch):
    import local_reconcile.business.matching as engine
    w=wide_pool(monkeypatch);w=replace(w,settings=replace(w.settings,project_budget=20))
    original=engine.relation_basis;calls=[]
    def measured(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(engine,'relation_basis',measured)
    result=suggest_matches(w)
    assert result.ranges and len(calls)<=20


def test_cancellation_checked_inside_candidate_pool(monkeypatch):
    from concurrent.futures import CancelledError
    import local_reconcile.business.matching as engine
    w=wide_pool(monkeypatch);original=engine.relation_basis;calls=[]
    def measured(*args):calls.append(1);return original(*args)
    monkeypatch.setattr(engine,'relation_basis',measured)
    with pytest.raises(CancelledError):suggest_matches(w,cancelled=lambda:bool(calls))
    assert len(calls)<=150
