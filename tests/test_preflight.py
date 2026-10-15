from dataclasses import replace
import pytest
from conftest import raw_table,mapping,dataset
from local_reconcile.domain import RawCell,RawRow
from local_reconcile.normalize import normalize
from local_reconcile.preflight import preflight

def test_explicit_direction():
    t=raw_table("bank",[["2026-10-15","10","甲","1",""]])
    assert normalize(t,mapping(direction="inverted")).transactions[0].amount_minor==-1000
    t=raw_table("bank",[["2026-10-15","10","","甲","1",""]],("日期","收","支","对方","编号","摘要"))
    m=mapping(amount_col=None,income_col=1,expense_col=2,party_col=3,reference_col=4,summary_col=5,direction="income_expense")
    assert normalize(t,m).transactions[0].amount_minor==1000
    t=replace(t,rows=(replace(t.rows[0],cells=(RawCell("2026-10-15"),RawCell(""),RawCell("10"),RawCell("甲"),RawCell("1"),RawCell(""))),))
    assert normalize(t,m).transactions[0].amount_minor==-1000

@pytest.mark.parametrize("day,amount",[("bad","1"),("2026-10-15","0.001"),("2026-10-15","")])
def test_no_silent_bad_row(day,amount):
    d=dataset("bank",[[day,amount,"甲","1",""]])
    assert any(i.severity=="error" and "bank-0" in i.row_ids for i in d.issues)
    assert len(d.raw.rows)==1

def test_missing_declarations():
    t=raw_table("bank",[["2026-10-15","10","甲","1",""]])
    for m in (mapping(confirmed=False),mapping(declared_account=""),mapping(date_col=90)):
        assert any(i.severity=="error" for i in normalize(t,m).issues)

def test_account_currency_conflict():
    b=dataset("bank",[["2026-10-15","10","甲","1",""]])
    l=dataset("ledger",[["2026-10-15","10","甲","1",""]],declared_account="different")
    assert any(i.severity=="error" for i in preflight(b,l))
    l=dataset("ledger",[["2026-10-15","10","甲","1",""]],declared_currency="USD")
    assert any(i.severity=="error" for i in preflight(b,l))

def test_numeric_identifier_precision():
    d=dataset("bank",[["2026-10-15","10","甲","00123",""]])
    assert d.transactions[0].reference=="00123"
    d=dataset("bank",[["2026-10-15","10","甲",12345678901234567,""]])
    assert any(i.code=="identifier_precision" for i in d.issues)

def test_formula_missing_cache_blocks():
    t=raw_table("bank",[["2026-10-15","10","甲","1",""]])
    cells=list(t.rows[0].cells);cells[1]=RawCell("=1+1","formula",None)
    t=replace(t,rows=(replace(t.rows[0],cells=tuple(cells)),))
    assert any(i.severity=="error" for i in normalize(t,mapping()).issues)

def test_nontrade_rows_and_dual_amount_block():
    t=raw_table("bank",[["","","","",""],["2026-10-15","10","3","",""]])
    m=mapping(amount_col=None,income_col=1,expense_col=2,party_col=None,reference_col=None,summary_col=None,direction="income_expense")
    d=normalize(t,m)
    assert any(i.code=="blank_row" for i in d.issues)
    assert any(i.severity=="error" and i.row_ids==("bank-1",) for i in d.issues)
