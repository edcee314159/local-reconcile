from datetime import date
import pytest
from local_reconcile.dates import parse_date
from local_reconcile.domain import LocalReconcileError

def test_unambiguous_dates():
    assert parse_date("2026-10-15") == date(2026,10,15)
    assert parse_date("2026/10/15") == date(2026,10,15)
    assert parse_date("2026年10月15日") == date(2026,10,15)

def test_ambiguous_date():
    with pytest.raises(LocalReconcileError):
        parse_date("01/02/2026")
    assert parse_date("01/02/2026","%d/%m/%Y") == date(2026,2,1)

def test_excel_epochs():
    assert parse_date(1, excel_epoch=date(1899,12,30)) == date(1900,1,1)
    assert parse_date(1, excel_epoch=date(1904,1,1)) == date(1904,1,2)
    with pytest.raises(LocalReconcileError):
        parse_date(45100)

@pytest.mark.parametrize("value", ["2026-02-30", True, ""])
def test_invalid_date(value):
    with pytest.raises(LocalReconcileError):
        parse_date(value)
