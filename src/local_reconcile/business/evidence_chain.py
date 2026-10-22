"""Manually reviewed business documents and bank proofs; never financial postings."""
from collections import defaultdict
from copy import deepcopy
from .workspace import active_records, period_end, _integer, _note, fail
from ..matching import stable_id

KINDS = ('合同', '订单', '收货', '验收', '发票', '付款', '收款', '退款')
CASH_KINDS = ('付款', '收款', '退款')


def _group_id(r):
    return stable_id('evidence-group', r.party, r.extra['business'], r.extra['direction'])


def _is_document(r):
    return r.role == 'business_evidence'


def _groups(active):
    groups = defaultdict(list)
    for r in active.values():
        if _is_document(r):
            groups[_group_id(r)].append(r)
    return groups


def _version(s, group):
    s.evidence_versions[group] = s.evidence_versions.get(group, 0) + 1


def _fingerprint(s, group, rows, rule, links):
    sources = tuple(sorted((r.id, r.day.isoformat(), r.amount_minor, r.party, r.reference,
                            r.extra['business'], r.extra['direction'], r.extra['kind']) for r in rows))
    proofs = tuple(sorted((key, link['document'], link['cash'], link['amount_minor'], link['evidence']) for key, link in links.items()))
    return (s.evidence_versions.get(group, 0), rule['seq'] if rule else None, sources, proofs)


def evidence_report(w, period=None, state=None):
    s = state or w.state
    period = period or s.period
    if period in s.closings:
        return deepcopy(s.closings[period].get('evidence', {'period': period, 'groups': []}))
    if period != s.period:
        fail('只可查看当前期间或已保存的历史期间')
    active = active_records(w, s)
    result = []
    for group, rows in sorted(_groups(active).items()):
        rows.sort(key=lambda r: r.id)
        first = rows[0]
        ids = {r.id for r in rows}
        rule = s.evidence_rules.get(group)
        contracts = [r for r in rows if r.extra['kind'] == '合同']
        selected_id = (rule['contract'] if rule else '') or (contracts[0].id if len(contracts) == 1 else '')
        contract = next((r for r in contracts if r.id == selected_id), None)
        limit = contract.amount_minor if contract else None
        totals = {kind: sum(r.amount_minor for r in rows if r.extra['kind'] == kind) for kind in KINDS}
        missing = tuple(kind for kind in rule['required'] if not any(r.extra['kind'] == kind for r in rows)) if rule else ()
        links = {key: link for key, link in s.evidence_cash_links.items() if link['document'] in ids}
        verified = 0
        linked_face = 0
        invalid_proof = False
        for link in links.values():
            document, cash = active.get(link['document']), active.get(link['cash'])
            if not document or not cash or cash.role != 'bank' or (cash.amount_minor > 0) != (_bank_sign(document) > 0):
                invalid_proof = True
                continue
            verified += link['amount_minor'] * (-1 if document.extra['kind'] == '退款' else 1)
            linked_face += link['amount_minor']
        declared = totals['收款'] + totals['付款'] - totals['退款']
        unlinked = sum(totals[kind] for kind in CASH_KINDS) - linked_face
        flags = []
        if len(contracts) > 1 and not contract:
            flags.append('存在多个合同需明确选择')
        if selected_id and not contract:
            flags.append('所选合同来源已不可用')
        if missing:
            flags.append('缺少必需单据')
        if rule and '验收' in rule['required'] and not any(r.extra['kind'] == '验收' for r in rows) and totals['收款'] + totals['付款'] > 0:
            flags.append('验收缺失但已有收付款单据')
        if limit is not None and totals['发票'] > limit:
            flags.append('发票净额超过合同金额')
        if limit is not None and verified > limit:
            flags.append('已核实收付款净额超过合同金额')
        if unlinked > 0:
            flags.append('收付款单据尚缺银行资金证明')
        if invalid_proof:
            flags.append('银行资金证明来源需重新核实')
        if totals['发票'] < 0:
            flags.append('发票净额为负需复核')
        if declared < 0 or verified < 0:
            flags.append('退款后收付款净额为负需复核')
        confirmation = s.evidence_confirmations.get(group)
        valid = bool(confirmation and rule and not flags and confirmation['fingerprint'] == _fingerprint(s, group, rows, rule, links))
        if not rule:
            status = '检查规则待确认'
        elif confirmation and not valid:
            status = '证据链已变化需复核'
        elif valid:
            status = '证据链已确认'
        elif flags:
            status = '存在待补证或核实事项'
        else:
            status = '证据齐备待确认'
        result.append({'id': group, 'period': period, 'party': first.party, 'business': first.extra['business'],
                       'direction': first.extra['direction'], 'rows': tuple(r.id for r in rows),
                       'contract': contract.id if contract else '', 'limit_minor': limit, 'totals': totals,
                       'invoice_minor': totals['发票'], 'declared_paid_minor': declared,
                       'verified_paid_minor': verified, 'cash_unlinked_minor': unlinked, 'missing': missing,
                       'flags': tuple(flags), 'status': status, 'evidence': rule['evidence'] if rule else '',
                       'confirmation_evidence': confirmation['evidence'] if confirmation else '',
                       'review_valid': valid, 'cash_links': tuple(sorted(links)), 'cash_link_details': deepcopy(links),
                       'required': tuple(rule['required']) if rule else ()})
    return {'period': period, 'groups': result}


def _bank_sign(document):
    sign = 1 if document.extra['direction'] == 'receivable' else -1
    return -sign if document.extra['kind'] == '退款' else sign


def _existing_group(w, s, group):
    if not isinstance(group, str):
        fail('请选择当前业务证据链分组')
    found = next((g for g in evidence_report(w, state=s)['groups'] if g['id'] == group), None)
    if found is None:
        fail('请选择当前可用的业务证据链分组')
    return found


def apply_evidence(w, s, e, active):
    d = e.data
    if e.kind == 'register_evidence_rule':
        group = d.get('group')
        row = _existing_group(w, s, group)
        required = d.get('required')
        if not isinstance(required, (list, tuple)) or not 1 <= len(required) <= len(KINDS) or any(not isinstance(k, str) or k not in KINDS for k in required) or len(set(required)) != len(required):
            fail('必需单据须选择 1—8 种且不能重复')
        contract = d.get('contract', '')
        if not isinstance(contract, str):
            fail('请选择本组合同')
        contracts = [rid for rid in row['rows'] if active[rid].extra['kind'] == '合同']
        if not contract and len(contracts) == 1:
            contract = contracts[0]
        if (len(contracts) > 1 and not contract) or (contract and contract not in contracts):
            fail('存在多个合同须明确选择本组合同，不可跨业务或方向选择')
        evidence = _note(d, 'evidence', True)
        s.evidence_rules[group] = {'required': tuple(required), 'contract': contract, 'evidence': evidence, 'seq': e.seq, 'period': s.period}
        _version(s, group)
    elif e.kind == 'undo_evidence_rule':
        group = d.get('target')
        if not isinstance(group, str) or group not in s.evidence_rules:
            fail('证据检查规则不存在或已撤销')
        if group in s.evidence_confirmations:
            fail('请先撤销证据链确认')
        _note(d, 'note', True)
        del s.evidence_rules[group]
        _version(s, group)
    elif e.kind == 'link_evidence_cash':
        document_id, cash_id = d.get('document'), d.get('cash')
        if not isinstance(document_id, str) or not isinstance(cash_id, str):
            fail('请选择收付款单据及银行流水')
        document, cash = active.get(document_id), active.get(cash_id)
        if not document or not _is_document(document) or document.extra['kind'] not in CASH_KINDS or not cash or cash.role != 'bank':
            fail('须选择当前可用的收付款或退款单据及银行流水')
        if document.extra['direction'] not in ('receivable', 'payable') or (document.extra['kind'] == '付款' and document.extra['direction'] != 'payable') or (document.extra['kind'] == '收款' and document.extra['direction'] != 'receivable'):
            fail('收付款单据与应收应付方向不一致')
        amount = _integer(d.get('amount_minor'), True)
        evidence = _note(d, 'evidence', True)
        if not cash.amount_minor or (cash.amount_minor > 0) != (_bank_sign(document) > 0):
            fail('银行流水收付方向与单据不一致')
        document_used = sum(p['amount_minor'] for p in s.evidence_cash_links.values() if p['document'] == document_id)
        cash_used = sum(p['amount_minor'] for p in s.evidence_cash_links.values() if p['cash'] == cash_id)
        if document_used + amount > document.amount_minor or cash_used + amount > abs(cash.amount_minor):
            fail('资金证明金额不能超过单据金额或银行流水可证明金额')
        s.evidence_cash_links[f'evidence-cash-{e.seq}'] = {'document': document_id, 'cash': cash_id, 'amount_minor': amount, 'evidence': evidence, 'period': s.period}
        _version(s, _group_id(document))
    elif e.kind == 'undo_evidence_cash':
        target = d.get('target')
        if not isinstance(target, str) or target not in s.evidence_cash_links:
            fail('凭证资金关联不存在或已撤销')
        _note(d, 'note', True)
        document = w.records[s.evidence_cash_links[target]['document']]
        _version(s, _group_id(document))
        del s.evidence_cash_links[target]
    elif e.kind == 'confirm_evidence_chain':
        group = d.get('group')
        row = _existing_group(w, s, group)
        evidence = _note(d, 'evidence', True)
        rule = s.evidence_rules.get(group)
        if not rule or row['missing'] or row['flags']:
            fail('请先确认检查规则、补齐必需单据并核实全部提示事项')
        rows = [active[rid] for rid in row['rows']]
        links = {key: s.evidence_cash_links[key] for key in row['cash_links']}
        s.evidence_confirmations[group] = {'evidence': evidence, 'period': s.period, 'seq': e.seq,
            'fingerprint': _fingerprint(s, group, rows, rule, links),
            'rows': tuple(sorted(set(row['rows']) | {p['cash'] for p in links.values()}))}
    elif e.kind == 'undo_evidence_confirmation':
        group = d.get('target')
        if not isinstance(group, str) or group not in s.evidence_confirmations:
            fail('证据链确认不存在或已撤销')
        _note(d, 'note', True)
        del s.evidence_confirmations[group]
    else:
        fail('不支持的业务证据链操作')


def touch_evidence(w, s, e):
    """Monotonic source revisions prevent an exclusion/restore from reviving review."""
    if e.kind in ('exclude', 'undo_exclude'):
        row = w.records.get(e.data.get('row'))
        changed = [row] if row else []
    elif e.kind == 'import_batch':
        changed = [r for r in w.records.values() if r.batch_id == e.data.get('batch') and r.id in s.visible and r.day <= period_end(s.period)]
    else:
        return
    changed_ids = {r.id for r in changed}
    groups = {_group_id(r) for r in changed if _is_document(r)}
    groups.update(group for group, confirmation in s.evidence_confirmations.items() if changed_ids.intersection(confirmation['rows']))
    groups.update(_group_id(w.records[link['document']]) for link in s.evidence_cash_links.values() if link['cash'] in changed_ids)
    for group in groups:
        _version(s, group)


def occupied_evidence(s):
    occupied = {r['contract'] for r in s.evidence_rules.values() if r.get('contract')}
    for confirmation in s.evidence_confirmations.values():
        occupied.update(confirmation['rows'])
    for link in s.evidence_cash_links.values():
        occupied.update((link['document'], link['cash']))
    return occupied
