import pytest
from test_contract_terms import source,base
from local_reconcile.business.workspace import record_event,new_workspace
from local_reconcile.domain import LocalReconcileError


@pytest.mark.parametrize('kind,amount,direction',[('合同','0','应收'),('收款','0','应收'),('退款','-1','应付'),('发票','0','应收'),('订单','-1','应收'),('收货','-1','应付'),('付款','10','应收'),('收款','10','应付'),('不存在','1','应收'),('验收','1','未知')])
def test_reject_invalid_evidence_source(kind,amount,direction):
    with pytest.raises(LocalReconcileError):source(new_workspace('2026-10'),kind,amount,direction=direction)


def test_credit_invoice_zero_acceptance_and_normalized_direction():
    w=source(base(),'发票','-20','INV')
    w=source(w,'验收','0','ACCEPT',direction='receivable')
    assert next(r for r in w.records.values() if r.reference=='INV').amount_minor==-2000
    assert next(r for r in w.records.values() if r.reference=='ACCEPT').extra['direction']=='receivable'


def test_doc_cannot_be_reimported_under_another_business():
    w=base()
    with pytest.raises(LocalReconcileError):source(w,'合同',business='OTHER')


def test_missing_identifiers_not_silently_accepted():
    for kwargs in ({'business':''},{'reference':''},{'party':''}):
        with pytest.raises(LocalReconcileError):source(new_workspace('2026-10'),'合同',**kwargs)


def test_late_evidence_does_not_rewrite_closing():
    w=record_event(base(),'close_period');old=w.state.closings.copy()
    w=record_event(w,'advance_period',period='2026-11')
    w=source(w,'验收','0','LATE',day='2026-10-20')
    assert w.state.closings==old and len(w.state.visible)==2
