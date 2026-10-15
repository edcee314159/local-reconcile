from dataclasses import replace
import pytest
from conftest import dataset
from local_reconcile.domain import ProjectSnapshot,MatchConfig,ReviewEvent,LocalReconcileError
from local_reconcile.matching import reconcile
from local_reconcile.review import apply_review,classify_rows,confirm_batch

def project(b=None,l=None):
    b=dataset("bank",b or [["2026-10-15","10","甲","A",""]])
    l=dataset("ledger",l or [["2026-10-15","10","甲","A",""]])
    config=MatchConfig()
    return ProjectSnapshot(1,b,l,config,reconcile(b,l,config))

def event(s,kind,b="bank-0",l="ledger-0",note=""):
    return ReviewEvent(len(s.review.events)+1,kind,b,l,note)

def test_single_use_per_row():
    s=project(l=[["2026-10-15","10","甲","A",""],["2026-10-15","10","甲","A",""]])
    s=apply_review(s,event(s,"confirm"))
    assert len(s.review.pairs)==1
    with pytest.raises(LocalReconcileError):
        apply_review(s,event(s,"confirm",l="ledger-1"))

def test_reject_and_undo():
    s=project()
    s=apply_review(s,event(s,"reject",note="待核实"))
    assert classify_rows(s)["bank-0"]=="unmatched"
    s=apply_review(s,event(s,"undo"))
    assert classify_rows(s)["bank-0"]=="pending"
    s=apply_review(s,event(s,"confirm"))
    assert classify_rows(s)["bank-0"]=="confirmed"
    s=apply_review(s,event(s,"undo"))
    assert classify_rows(s)["bank-0"]=="pending"
    assert len(s.review.events)==4

def test_manual_pair_validation():
    s=project(l=[["2026-10-15","9","甲","A",""]])
    with pytest.raises(LocalReconcileError):
        apply_review(s,event(s,"confirm",note="人工指定"))
    s=project()
    with pytest.raises(LocalReconcileError):
        apply_review(s,event(s,"confirm",l="nonexistent"))

def test_batch_strong_only():
    s=project()
    out=confirm_batch(s,(s.result.candidates[0].id,))
    assert len(out.review.pairs)==1 and not s.review.pairs
    weak=project(b=[["2026-10-15","10","","",""]],l=[["2026-10-15","10","","",""]])
    with pytest.raises(LocalReconcileError):
        confirm_batch(weak,(weak.result.candidates[0].id,))
    amb=project(b=[["2026-10-15","10","甲","A",""]]*2)
    with pytest.raises(LocalReconcileError):
        confirm_batch(amb,tuple(c.id for c in amb.result.candidates))

def test_mutually_exclusive_counts():
    s=project(b=[["2026-10-15","10","甲","A",""],["2026-10-15","99","乙","B",""]])
    s=apply_review(s,event(s,"confirm"))
    states=classify_rows(s)
    assert sorted(states.values())==["confirmed","confirmed","unmatched"]
    assert len(states)==3
