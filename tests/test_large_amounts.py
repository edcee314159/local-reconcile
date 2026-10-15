from local_reconcile.amounts import parse_amount

def test_large_amount_never_rounds_last_cent():
    assert parse_amount("1234567890123456789012345678.91")==123456789012345678901234567891
    assert parse_amount("-1234567890123456789012345678.91")==-123456789012345678901234567891
