import pytest
from local_reconcile.amounts import parse_amount
from local_reconcile.domain import LocalReconcileError

@pytest.mark.parametrize("value,want", [("1,234.56",123456),("-0.01",-1),("0",0),(12.34,1234),(" ￥ 10.00 ",1000),("(20.00)",-2000)])
def test_exact_cents(value, want):
    assert parse_amount(value) == want

@pytest.mark.parametrize("value", ["0.001","1,23.00",True,"NaN","Infinity","abc","",None,"1e3"])
def test_reject_subcent_and_invalid(value):
    with pytest.raises(LocalReconcileError):
        parse_amount(value)
