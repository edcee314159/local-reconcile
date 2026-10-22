"""Business evidence rules prove documents and bank facts without posting balances."""
from copy import deepcopy
from datetime import date
from importlib.util import find_spec
from types import SimpleNamespace
import pytest
from local_reconcile.business.models import Record, State, Event
from local_reconcile.business.workspace import active_records
from local_reconcile.domain import LocalReconcileError


def test_evidence_kernel_is_available():
    assert find_spec('local_reconcile.business.evidence_chain') is not None


class Book:
    def __init__(self):
        self.state = State('2026-10')
        for field in ('evidence_rules', 'evidence_cash_links', 'evidence_confirmations', 'evidence_versions'):
            setattr(self.state, field, {})
        self.records = {}
        self.batches = ()
        self.seq = 0

    def add(self, rid, kind='合同', amount=10000, direction='receivable', party='甲', business='B1', day='2026-10-01', role='business_evidence'):
        self.records[rid] = Record(rid, 'batch', rid, role, 'BANK' if role == 'bank' else '', date.fromisoformat(day), amount, party, rid, rid,
                                  extra={'kind': kind, 'business': business, 'direction': direction} if role == 'business_evidence' else {})
        self.state.visible.add(rid)
        return self

    def event(self, kind, **data):
        from local_reconcile.business.evidence_chain import apply_evidence, touch_evidence
        self.seq += 1
        e = Event(self.seq, kind, data)
        apply_evidence(self, self.state, e, active_records(self))
        touch_evidence(self, self.state, e)
        return self

    def group(self, business='B1'):
        from local_reconcile.business.evidence_chain import evidence_report
        return next(g for g in evidence_report(self)['groups'] if g['business'] == business)

    def rule(self, required=('合同',), contract='', evidence='人工核实规则'):
        return self.event('register_evidence_rule', group=self.group()['id'], required=list(required), contract=contract, evidence=evidence)

    def proof(self, document='payment', cash='bank', amount=10000, evidence='银行及单据核实'):
        return self.event('link_evidence_cash', document=document, cash=cash, amount_minor=amount, evidence=evidence)

    def confirm(self, evidence='业务负责人复核'):
        return self.event('confirm_evidence_chain', group=self.group()['id'], evidence=evidence)


def paid(direction='receivable', amount=10000):
    return Book().add('contract', direction=direction).add('payment', '收款' if direction == 'receivable' else '付款', amount, direction).add('bank', amount=amount if direction == 'receivable' else -amount, role='bank')


def test_unconfigured_group_never_claims_complete():
    b = Book().add('contract')
    assert b.group()['status'] == '检查规则待确认'
    assert b.group()['limit_minor'] == 10000
    with pytest.raises(LocalReconcileError): b.confirm()


def test_manual_required_kinds_and_unique_contract_selection():
    b = Book().add('contract').add('invoice', '发票', 8000).rule(('合同', '发票'))
    g = b.group()
    assert g['contract'] == 'contract' and g['missing'] == () and g['invoice_minor'] == 8000
    assert g['status'] == '证据齐备待确认'
    assert b.confirm().group()['review_valid']


def test_missing_required_contract_and_acceptance_block_confirmation():
    b = Book().add('payment', '收款', 1000).rule(('合同', '验收'))
    assert set(b.group()['missing']) == {'合同', '验收'}
    assert b.group()['status'] == '存在待补证或核实事项'
    with pytest.raises(LocalReconcileError): b.confirm()


def test_multiple_contracts_require_explicit_same_group_selection():
    b = Book().add('contract').add('second').add('other', business='B2')
    assert b.group()['limit_minor'] is None and b.group()['flags']
    with pytest.raises(LocalReconcileError): b.rule()
    with pytest.raises(LocalReconcileError): b.rule(contract='other')
    assert b.rule(contract='second').group()['contract'] == 'second'


@pytest.mark.parametrize('required,contract,evidence', [([], '', '核实'), (['合同', '合同'], '', '核实'), (['未知'], '', '核实'), (['合同'], 'missing', '核实'), (['合同'], '', ' ')])
def test_invalid_rule_payload_rejected(required, contract, evidence):
    with pytest.raises(LocalReconcileError): Book().add('contract').rule(required, contract, evidence)


def test_signed_credit_invoice_offsets_face_before_contract_limit_check():
    b = Book().add('contract').add('invoice', '发票', 12000).add('credit', '发票', -3000).rule(('合同', '发票'))
    assert b.group()['invoice_minor'] == 9000 and not b.group()['flags']
    assert b.confirm().group()['status'] == '证据链已确认'
    b.add('extra_invoice', '发票', 2000)
    assert b.group()['flags'] and not b.group()['review_valid']


def test_negative_invoice_and_refund_net_remain_explicit_review_flags():
    b = Book().add('contract').add('credit', '发票', -100).add('refund', '退款', 500).add('out', amount=-500, role='bank').rule()
    b.proof('refund', 'out', 500)
    assert b.group()['invoice_minor'] == -100
    assert b.group()['declared_paid_minor'] == -500 and b.group()['verified_paid_minor'] == -500
    with pytest.raises(LocalReconcileError): b.confirm()


def test_unverified_payment_is_not_real_cash_and_never_posts_financial_balances():
    b = paid().rule(('合同', '收款'))
    g = b.group()
    assert (g['declared_paid_minor'], g['verified_paid_minor'], g['cash_unlinked_minor']) == (10000, 0, 10000)
    with pytest.raises(LocalReconcileError): b.confirm()
    b.proof(amount=4000)
    assert b.group()['verified_paid_minor'] == 4000 and b.group()['cash_unlinked_minor'] == 6000
    assert not b.state.allocations and not b.state.advances and not b.state.refunds


@pytest.mark.parametrize('direction', ['receivable', 'payable'])
def test_payment_and_refund_bank_directions(direction):
    b = paid(direction).rule()
    b.proof()
    b.add('refund', '退款', 2000, direction).add('refund_bank', amount=-2000 if direction == 'receivable' else 2000, role='bank')
    b.proof('refund', 'refund_bank', 2000)
    assert b.group()['verified_paid_minor'] == 8000 and b.group()['cash_unlinked_minor'] == 0
    assert b.confirm().group()['review_valid']


@pytest.mark.parametrize('document,cash,amount,evidence', [('contract', 'bank', 1, '核实'), ('payment', 'missing', 1, '核实'), ('payment', 'bank', True, '核实'), ('payment', 'bank', 0, '核实'), ('payment', 'bank', 1.0, '核实'), ('payment', 'bank', 1, ' ')])
def test_proof_requires_cash_document_bank_integer_cents_and_evidence(document, cash, amount, evidence):
    with pytest.raises(LocalReconcileError): paid().proof(document, cash, amount, evidence)


def test_wrong_bank_sign_and_future_bank_rejected():
    b = paid().add('wrong', amount=-10000, role='bank').add('future', amount=10000, role='bank', day='2026-11-01')
    with pytest.raises(LocalReconcileError): b.proof(cash='wrong')
    with pytest.raises(LocalReconcileError): b.proof(cash='future')


def test_partial_proof_is_bounded_by_document_and_bank_across_groups():
    b = paid().add('other_payment', '收款', 10000, business='B2')
    b.proof(amount=6000)
    with pytest.raises(LocalReconcileError): b.proof(amount=4001)
    with pytest.raises(LocalReconcileError): b.proof('other_payment', amount=4001)
    b.proof('other_payment', amount=4000)
    assert b.group()['verified_paid_minor'] == 6000


def test_verified_total_over_contract_prevents_confirmation():
    b = paid(amount=12000).rule().proof(amount=12000)
    assert b.group()['verified_paid_minor'] == 12000
    with pytest.raises(LocalReconcileError): b.confirm()


def test_rule_change_and_restoration_do_not_revive_confirmation():
    b = Book().add('contract').rule().confirm()
    b.rule(evidence='重新确认规则')
    assert not b.group()['review_valid'] and b.group()['status'] == '证据链已变化需复核'
    b.rule()
    assert not b.group()['review_valid']


def test_proof_undo_relink_never_revives_confirmation_and_undo_requires_note():
    b = paid().rule().proof().confirm()
    link = b.group()['cash_links'][0]
    with pytest.raises(LocalReconcileError): b.event('undo_evidence_cash', target=link, note=' ')
    b.event('undo_evidence_cash', target=link, note='改正银行关联').proof()
    assert not b.group()['review_valid']
    assert b.confirm().group()['review_valid']


def test_source_exclude_restore_revision_does_not_revive_review():
    from local_reconcile.business.evidence_chain import touch_evidence
    b = Book().add('contract').rule().confirm()
    b.state.excluded.add('contract')
    touch_evidence(b, b.state, Event(100, 'exclude', {'row': 'contract'}))
    b.state.excluded.remove('contract')
    touch_evidence(b, b.state, Event(101, 'undo_exclude', {'row': 'contract'}))
    assert not b.group()['review_valid']


def test_future_required_document_only_satisfies_rule_when_activated():
    b = Book().add('contract').add('accept', '验收', 0, day='2026-11-01').rule(('合同', '验收'))
    assert b.group()['missing'] == ('验收',)
    b.state.period = '2026-11'
    assert b.group()['missing'] == ()
    assert b.confirm().group()['review_valid']
    b.add('future_invoice', '发票', 10, day='2026-12-01')
    assert b.group()['review_valid']
    b.state.period = '2026-12'
    assert not b.group()['review_valid']


def test_confirmed_sources_rule_contract_and_proof_banks_are_occupied():
    from local_reconcile.business.evidence_chain import occupied_evidence
    b = paid().add('invoice', '发票', 5000).rule().proof().confirm()
    assert {'contract', 'invoice', 'payment', 'bank'} <= occupied_evidence(b.state)
    with pytest.raises(LocalReconcileError): b.event('undo_evidence_rule', target=b.group()['id'], note='撤销')
    b.event('undo_evidence_confirmation', target=b.group()['id'], note='撤销确认')
    b.event('undo_evidence_rule', target=b.group()['id'], note='撤销规则')
    assert {'payment', 'bank'} <= occupied_evidence(b.state)
    assert 'invoice' not in occupied_evidence(b.state)


def test_historical_snapshots_are_deep_copied_and_legacy_empty_is_supported():
    from local_reconcile.business.evidence_chain import evidence_report
    b = Book().add('contract').rule().confirm()
    saved = deepcopy(evidence_report(b))
    b.state.closings['2026-10'] = {'evidence': saved}
    b.state.closings['2026-09'] = {}
    b.state.period = '2026-11'
    old = evidence_report(b, '2026-10')
    old['groups'][0]['totals'].clear()
    assert evidence_report(b, '2026-10') == saved
    assert evidence_report(b, '2026-09') == {'period': '2026-09', 'groups': []}
    with pytest.raises(LocalReconcileError): evidence_report(b, '2026-08')


def test_bank_exclusion_restoration_never_revives_confirmation():
    from local_reconcile.business.evidence_chain import touch_evidence
    b = paid().rule().proof().confirm()
    b.state.excluded.add('bank')
    touch_evidence(b, b.state, Event(100, 'exclude', {'row': 'bank'}))
    assert not b.group()['review_valid'] and b.group()['verified_paid_minor'] == 0
    b.state.excluded.remove('bank')
    touch_evidence(b, b.state, Event(101, 'undo_exclude', {'row': 'bank'}))
    assert not b.group()['review_valid']


def test_document_face_caps_proof_even_when_other_bank_has_capacity():
    b = paid().add('second_bank', amount=10000, role='bank').proof(amount=6000)
    with pytest.raises(LocalReconcileError): b.proof(cash='second_bank', amount=4001)
    b.proof(cash='second_bank', amount=4000)
    assert b.group()['verified_paid_minor'] == 10000


def test_event_replay_storage_history_and_proof_independence(tmp_path):
    from conftest import raw_table, mapping
    from test_business import base, add, ids
    from local_reconcile.business.workspace import add_batch, record_event
    from local_reconcile.business.storage import save_workspace, load_workspace
    from local_reconcile.business.operations import cash_remaining
    from local_reconcile.business.evidence_chain import evidence_report
    w = add(base(), 'bank', [['2026-10-02', '100', '银行别名', 'BANK', '']])
    w = add(w, 'receivable', [['2026-10-02', '100', '甲', 'INVOICE', '']])
    raw = raw_table('ledger', [['2026-10-01', '100', '甲', 'C1', '合同原件', 'B1', '合同', '应收'],
                               ['2026-10-02', '100', '甲', 'P1', '收款凭据', 'B1', '收款', '应收']],
                    ('日期', '金额', '单位', '编号', '摘要', '业务', '单据类型', '方向'))
    w = add_batch(w, 'business_evidence', '', raw, mapping(declared_account='OPEN-ITEMS'),
                  extra_cols={'business': 5, 'kind': 6, 'direction': 7})
    group = evidence_report(w)['groups'][0]['id']
    document = next(r.id for r in w.records.values() if r.reference == 'P1')
    bank = ids(w, 'bank')[0]
    w = record_event(w, 'register_evidence_rule', group=group, required=['合同', '收款'], contract='', evidence='原件已检查')
    w = record_event(w, 'link_evidence_cash', document=document, cash=bank, amount_minor=10000, evidence='付款人银行别名已核实')
    w = record_event(w, 'confirm_evidence_chain', group=group, evidence='人工逐项复核')
    assert cash_remaining(w, bank) == 10000 and not w.state.allocations
    w = record_event(w, 'allocate', cash=bank, item=ids(w, 'receivable')[0], amount_minor=10000, note='另行核销')
    assert evidence_report(w)['groups'][0]['review_valid']
    saved = deepcopy(evidence_report(w))
    link = saved['groups'][0]['cash_links'][0]
    w = record_event(record_event(w, 'close_period'), 'advance_period', period='2026-11')
    w = record_event(w, 'undo_evidence_cash', target=link, note='本期更正资金证明')
    assert evidence_report(w, '2026-10') == saved
    assert evidence_report(w, '2026-10')['groups'][0]['cash_link_details'][link]['amount_minor'] == 10000
    path = tmp_path / 'evidence.lrwork'
    save_workspace(w, path)
    restored = load_workspace(path)
    assert evidence_report(restored) == evidence_report(w)
    assert evidence_report(restored, '2026-10') == saved


def test_later_unique_contract_applies_limit_to_existing_rule():
    b = Book().add('invoice', '发票', 12000).rule(('合同', '发票'))
    assert b.group()['missing'] == ('合同',) and b.group()['limit_minor'] is None
    b.add('contract')
    assert b.group()['contract'] == 'contract' and b.group()['limit_minor'] == 10000
    with pytest.raises(LocalReconcileError): b.confirm()
