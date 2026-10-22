"""Real Qt audit pages and atomic correction actions; no source-directory artifacts."""
from copy import deepcopy
from threading import Event

import pytest
from PySide6.QtWidgets import QScrollArea
from test_ui_flow import app, wait_until
from test_contract_terms import base, bank, source, rid
from test_corrections import fixture as correction_fixture
from test_settlements import cashbook, refund
from local_reconcile.ui.business_window import BusinessWindow
from local_reconcile.business.workspace import new_workspace, record_event, add_account
from local_reconcile.business.evidence_chain import evidence_report
from local_reconcile.business.contract_terms import contract_report
from local_reconcile.domain import LocalReconcileError


@pytest.fixture
def window(app):
    w = BusinessWindow()
    yield w
    w.dirty = False
    w.close()


def evidence_book():
    w = source(base(), '收款', '30', 'P1')
    w = source(w, '验收', '100', 'AC1')
    return bank(w)


def select(combo, key):
    index = combo.findData(key)
    assert index >= 0
    combo.setCurrentIndex(index)


def queue_change(w):
    data, first, second, _ = correction_fixture()
    w.set_workspace(data)
    w.dirty = False
    w.correction_reason.setText('核销对象经原件核查需更正')
    w.correction_amount.setText('40.00')
    select(w.correction_item, second)
    w.add_correction_step()
    return data, first, second


def test_empty_workspace_scroll_pages_and_string_ids(window):
    window.set_workspace(new_workspace('2026-10'))
    assert window.tabs.count() == 17
    assert len(window.findChildren(QScrollArea)) >= 5
    assert not window.evidence_save_button.isEnabled()
    assert not window.stage_add_button.isEnabled()
    assert not window.correction_apply_button.isEnabled()
    assert window.stage_base.minimumDate().year() == 1900
    assert window.stage_base.maximumDate().year() == 9999
    for combo in (window.evidence_period, window.contract_period):
        assert all(isinstance(combo.itemData(i), str) for i in range(combo.count()))
    with pytest.raises(LocalReconcileError): window.save_evidence_rule_selected()
    with pytest.raises(LocalReconcileError): window.add_contract_stage_selected()


def test_evidence_rule_bank_proof_confirmation_and_source_drilldown(window):
    window.set_workspace(evidence_book())
    window.evidence_required['合同'].setChecked(True)
    window.evidence_required['收款'].setChecked(True)
    window.evidence_rule_note.setText('合同与收款原件核实')
    window.save_evidence_rule_selected()
    window.evidence_amount.setText('30.00')
    window.evidence_cash_note.setText('银行收款核实')
    window.link_evidence_cash_selected()
    window.evidence_confirm_note.setText('负责人复核')
    window.confirm_evidence_selected()
    group = evidence_report(window.workspace)['groups'][0]
    assert group['review_valid'] and group['verified_paid_minor'] == 3000
    assert not window.workspace.state.allocations and not window.workspace.state.matches
    assert window.evidence_link_table.model().rowCount() == 1
    selected = window.evidence_group.currentData()
    window.refresh()
    assert window.evidence_group.currentData() == selected
    window.evidence_source_detail()
    assert 'ledger.csv' in window.detail.toPlainText()
    window.evidence_link_table.selectRow(0)
    window.evidence_link_detail()
    assert '银行收款核实' in window.detail.toPlainText()
    window.evidence_confirm_note.setText('撤销整组复核')
    window.undo_evidence_confirmation_selected()
    assert not evidence_report(window.workspace)['groups'][0]['review_valid']


def test_contract_condition_and_stage_proof_do_not_post_money(window):
    window.set_workspace(evidence_book())
    window.stage_name.setText('验收款')
    window.stage_amount.setText('60.00')
    window.stage_trigger.setCurrentText('验收')
    window.stage_delay.setValue(10)
    window.stage_note.setText('合同第2条已核实')
    window.add_contract_stage_selected()
    row = contract_report(window.workspace)['stages'][0]
    assert row['due_day'] is None and row['status'] == '条件未核实'
    window.stage_condition_note.setText('验收原件及条件已核实')
    select(window.stage_condition_doc, rid(window.workspace, 'AC1'))
    window.verify_stage_selected()
    window.stage_cash_amount.setText('20.01')
    window.stage_cash_note.setText('银行流水对应阶段')
    window.link_stage_cash_selected()
    row = contract_report(window.workspace)['stages'][0]
    assert row['due_day'] == '2026-10-11'
    assert row['paid_minor'] == 2001 and row['remaining_minor'] == 3999
    assert not window.workspace.state.allocations and not window.workspace.state.credits
    selected = window.stage_choice.currentData()
    window.refresh()
    assert window.stage_choice.currentData() == selected
    window.stage_source_detail()
    assert '验收原件及条件已核实' in window.detail.toPlainText()
    window.stage_cash_kind.setCurrentText('退回')
    assert window.stage_cash.count() == 0
    window.stage_condition_note.setText('重新复核条件')
    window.undo_stage_condition_selected()
    assert '未核实条件已有收付款' in contract_report(window.workspace)['stages'][0]['flags']


def test_history_readonly_actions_and_link_snapshots_remain_browsable(window):
    window.set_workspace(evidence_book())
    window.evidence_required['合同'].setChecked(True)
    window.evidence_rule_note.setText('合同规则')
    window.save_evidence_rule_selected()
    window.evidence_amount.setText('30'); window.evidence_cash_note.setText('当时的收款依据')
    window.link_evidence_cash_selected()
    evidence_link = next(iter(window.workspace.state.evidence_cash_links))
    window.stage_name.setText('首款'); window.stage_amount.setText('30'); window.stage_note.setText('首款条款')
    window.add_contract_stage_selected()
    window.stage_cash_amount.setText('20'); window.stage_cash_note.setText('当时的阶段依据')
    window.link_stage_cash_selected()
    stage_link = next(iter(window.workspace.state.stage_cash_links))
    window.apply('set_closing_balances', account='A', bank_minor=10000, ledger_minor=0, evidence='期末核实')
    window.apply('close_period')
    assert not window.correction_preview_button.isEnabled()
    window.apply('advance_period', period='2026-11')
    window.apply('undo_evidence_cash', target=evidence_link, note='本期更正')
    window.apply('undo_stage_cash', target=stage_link, note='本期更正')
    select(window.evidence_period, '2026-10'); select(window.contract_period, '2026-10')
    assert not window.evidence_save_button.isEnabled() and not window.stage_add_button.isEnabled()
    assert window.stage_choice.isEnabled()
    assert window.evidence_link_table.model().rowCount() == 1
    assert window.stage_link_table.model().rowCount() == 1
    assert window._evidence_links[evidence_link]['evidence'] == '当时的收款依据'
    assert window._stage_links[stage_link]['evidence'] == '当时的阶段依据'
    for action in (window.save_evidence_rule_selected, window.link_evidence_cash_selected, window.confirm_evidence_selected, window.add_contract_stage_selected, window.verify_stage_selected, window.link_stage_cash_selected):
        with pytest.raises(LocalReconcileError): action()


def test_real_async_correction_preview_preserves_original_then_apply(window, app, monkeypatch):
    from local_reconcile.business import corrections
    original, first, second = queue_change(window)
    before = deepcopy(original.state)
    preview = corrections.preview_correction
    seen = []
    def independent(workspace, *args, **kwargs):
        seen.append(workspace is not original)
        return preview(workspace, *args, **kwargs)
    monkeypatch.setattr(corrections, 'preview_correction', independent)
    assert [p['kind'] for p in window.correction_ops] == ['undo_allocate', 'allocate']
    window.preview_correction_selected()
    assert window.busy
    wait_until(app, lambda: not window.busy)
    assert seen == [True] and window.workspace is original
    assert original.state == before and not window.dirty
    assert window.correction_table.model().rowCount() > 0
    assert window.correction_apply_button.isEnabled()
    window.apply_correction_selected()
    assert window.dirty and len(window.workspace.state.corrections) == 1
    assert len(window.workspace.state.allocations) == 1
    assert next(iter(window.workspace.state.allocations.values()))['item'] == second
    assert not window.correction_ops and not window.correction_apply_button.isEnabled()
    assert window.correction_history_table.model().rowCount() == 1


def test_same_event_count_source_change_invalidates_preview_but_keeps_queue(window, app):
    original, _, _ = queue_change(window)
    window.preview_correction_selected(); wait_until(app, lambda: not window.busy)
    queue = deepcopy(window.correction_ops)
    changed = add_account(window.workspace, 'B', '新登记账户')
    assert len(changed.events) == len(original.events)
    window.set_workspace(changed)
    assert window.correction_preview_data is None and not window.correction_apply_button.isEnabled()
    assert window.correction_ops == queue and not window.dirty
    with pytest.raises(LocalReconcileError): window.apply_correction_selected()


def test_mutated_preview_token_and_reason_cannot_apply(window, app):
    original, _, _ = queue_change(window)
    window.preview_correction_selected(); wait_until(app, lambda: not window.busy)
    window.correction_preview_data['plan_token'] = 'changed'
    with pytest.raises(LocalReconcileError): window.apply_correction_selected()
    assert window.workspace is original and not window.dirty
    window.correction_reason.setText('原因改变')
    assert window.correction_preview_data is None and not window.correction_apply_button.isEnabled()


def test_refund_dependencies_display_without_cascade_or_mutation(window, app):
    w, original, reverse, item = cashbook()
    w = record_event(w, 'allocate', cash=original, item=item, amount_minor=10000, note='原核销')
    allocation = next(iter(w.state.allocations))
    w = refund(w, original, reverse, allocation=allocation)
    window.set_workspace(w); window.dirty = False
    window.correction_reason.setText('需先核查关联退款')
    window.correction_mode.setCurrentText('撤销核销')
    select(window.correction_target, allocation)
    window.add_correction_step(); window.preview_correction_selected()
    wait_until(app, lambda: not window.busy)
    assert not window.correction_preview_data['ok']
    assert window.correction_preview_data['blockers']
    assert '依赖' in window.correction_status.text()
    assert window.workspace is w and not window.dirty
    assert len(w.state.allocations) == 1 and len(w.state.refunds) == 1
    assert not window.correction_apply_button.isEnabled()


def test_cancelled_worker_never_enables_stale_apply(window, app, monkeypatch):
    from local_reconcile.business import corrections
    original, _, _ = queue_change(window)
    entered, release = Event(), Event()
    preview = corrections.preview_correction
    def slow(*args, **kwargs):
        entered.set()
        release.wait(5)
        return preview(*args, **kwargs)
    monkeypatch.setattr(corrections, 'preview_correction', slow)
    try:
        window.preview_correction_selected()
        wait_until(app, entered.is_set)
        window.cancel()
    finally:
        release.set()
    wait_until(app, lambda: not window.runner.jobs)
    assert window.workspace is original and not window.dirty
    assert window.correction_preview_data is None and not window.correction_apply_button.isEnabled()
