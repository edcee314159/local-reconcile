from dataclasses import replace
from datetime import date
import pytest
from conftest import dataset
from local_reconcile.domain import MatchConfig,LocalReconcileError
from local_reconcile.matching import reconcile

def run(b,l,config=MatchConfig()):
    return reconcile(dataset("bank",b),dataset("ledger",l),config)

def test_reference_match():
    r=run([["2026-10-15","10","甲","001",""]],[["2026-10-15","10","甲","001",""]])
    assert len(r.candidates)==1 and r.candidates[0].rule=="reference"
    assert not r.groups

def test_no_fallback_on_reference_conflict():
    r=run([["2026-10-15","10","甲","A",""]],[["2026-10-15","10","甲","B",""]])
    assert not r.candidates

def test_party_conflict_not_missing():
    assert not run([["2026-10-15","10","甲","",""]],[["2026-10-15","10","乙","",""]]).candidates
    r=run([["2026-10-15","10","甲","A",""]],[["2026-10-15","10","乙","A",""]])
    assert r.candidates[0].conflicts==("party",)

def test_same_amount_many_candidates():
    r=run([["2026-10-15","10","","",""]]*2,[["2026-10-15","10","","",""]]*2)
    assert len(r.candidates)==4
    assert len(r.groups)==1

def test_direction_and_date():
    b=[["2026-10-15","10","甲","A",""]]
    assert not run(b,[["2026-10-15","-10","甲","A",""]]).candidates
    assert not run(b,[["2026-10-16","10","甲","A",""]]).candidates
    assert len(run(b,[["2026-10-16","10","甲","A",""]],MatchConfig(1)).candidates)==1

def test_repeatable_result():
    b=[["2026-10-15","10","甲","A",""]]
    assert run(b,b)==run(b,b)

def test_group_limit():
    rows=[["2026-10-15","10","","",""]]*20
    r=run(rows,rows)
    assert not r.candidates
    assert len(r.groups)==1 and r.groups[0].truncated
    assert len(r.groups[0].bank_ids)==20 and len(r.groups[0].ledger_ids)==20

def test_amount_difference():
    r=run([["2026-10-15","10","甲","A",""]],[["2026-10-15","9","甲","A",""]])
    assert not r.candidates
    assert len(r.differences)==1 and r.differences[0].delta_minor==100

def test_invalid_data_and_config_block():
    with pytest.raises(LocalReconcileError):
        run([["bad","10","甲","A",""]],[["2026-10-15","10","甲","A",""]])
    with pytest.raises(LocalReconcileError):
        run([["2026-10-15","10","甲","A",""]],[["2026-10-15","10","甲","A",""]],MatchConfig(32))
