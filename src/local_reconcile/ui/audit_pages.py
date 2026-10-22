"""Evidence review, contract milestones and atomic correction simulation pages."""
from copy import deepcopy
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget
from .settlement_pages import _button, _row, _table, _populate, _options
from ..amounts import parse_amount, format_amount
from ..business.workspace import active_records, fail
from ..business.evidence_chain import evidence_report
from ..business.contract_terms import contract_report
from ..business import corrections
from ..business.credits import CREDIT_CATEGORIES

_KINDS = ("合同", "订单", "收货", "验收", "发票", "付款", "收款", "退款")
_TRIGGERS = ("签约", "到货", "验收", "开票", "质保届满", "自定日期")
_MODES = ("改核销单据", "撤销核销", "撤销退款", "红字抵减", "撤销红字抵减", "撤销预收预付", "撤销转账", "撤销阶段收付款", "撤销凭证资金关联")
_UNDOS = {"撤销核销": ("allocations", "undo_allocate"), "撤销退款": ("refunds", "undo_refund"), "撤销红字抵减": ("credits", "undo_credit_note"), "撤销预收预付": ("advances", "undo_advance"), "撤销转账": ("transfers", "undo_transfer"), "撤销阶段收付款": ("stage_cash_links", "undo_stage_cash"), "撤销凭证资金关联": ("evidence_cash_links", "undo_evidence_cash")}


def _money(value):
    return "未确定" if value is None else format_amount(value)


def _fill(table, headers, rows, keys):
    selected = table.selectionModel().selectedRows() if table.selectionModel() else ()
    old = getattr(table, "_audit_keys", [])
    key = old[selected[0].row()] if len(selected) == 1 and selected[0].row() < len(old) else None
    _populate(table, headers, rows)
    table._audit_keys = list(keys)
    if key in table._audit_keys:
        table.selectRow(table._audit_keys.index(key))


def _note(box, text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    box.addWidget(widget)
    return widget


def _form(box, fields):
    form = QFormLayout()
    for label, widget in fields:
        form.addRow(label, widget)
    box.addLayout(form)


def _audit_table(box):
    table = _table(box)
    table.setMinimumHeight(120)
    table.setMaximumHeight(220)
    return table


class AuditPages:
    def _audit_page(self, name):
        host = self._page(name)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        scroll.setWidget(content)
        host.addWidget(scroll, 1)
        return box

    def _audit_editable(self, period=None):
        s = self.workspace.state
        return (period is None or period.currentData() == "") and s.period not in s.closings

    def _audit_require_current(self, period=None):
        if not self._audit_editable(period):
            fail("历史月末快照只读，请切换到当前未结账期间")

    def _audit_period(self, combo):
        return combo.currentData() or None

    def _evidence_page(self):
        box = self._audit_page("业务凭证证据链")
        self.evidence_period = self._combo()
        self.evidence_group = self._combo()
        _row(box, QLabel("报告期间"), self.evidence_period, QLabel("单位 / 业务 / 方向"), self.evidence_group)
        self.evidence_status = _note(box, "请导入业务凭证，并人工确认检查规则。")
        _note(box, "银行关联只保存资金证明，不生成记账分录、不执行应收应付核销，也不占用原核销余额。凭证齐备与资金证明须分别核实。")
        self.evidence_table = _audit_table(box)
        self.evidence_required = {kind: QCheckBox(kind) for kind in _KINDS}
        required = QHBoxLayout()
        for control in self.evidence_required.values():
            required.addWidget(control)
        box.addLayout(required)
        self.evidence_contract = self._combo()
        self.evidence_rule_note = QLineEdit()
        _form(box, (("选定合同（多份合同时须指定）", self.evidence_contract), ("检查规则 / 撤销依据", self.evidence_rule_note)))
        self.evidence_save_button = _button(self, "登记 / 更新检查规则", self.save_evidence_rule_selected)
        self.evidence_undo_rule_button = _button(self, "撤销本组检查规则", self.undo_evidence_rule_selected)
        _row(box, self.evidence_save_button, self.evidence_undo_rule_button)
        self.evidence_doc = self._combo()
        self.evidence_cash = self._combo()
        self.evidence_amount = QLineEdit()
        self.evidence_cash_note = QLineEdit()
        self.evidence_cash_note.setPlaceholderText("银行回单、跨单位代收代付关系及关联依据；撤销时填写撤销原因")
        _form(box, (("付款 / 收款 / 退款凭证", self.evidence_doc), ("银行资金证明", self.evidence_cash), ("本次关联金额（元）", self.evidence_amount), ("资金关联 / 撤销依据", self.evidence_cash_note)))
        self.evidence_link_button = _button(self, "关联资金证明", self.link_evidence_cash_selected)
        self.evidence_unlink_button = _button(self, "撤销所选资金证明", self.undo_evidence_cash_selected)
        _row(box, self.evidence_link_button, self.evidence_unlink_button)
        self.evidence_link_table = _audit_table(box)
        self.evidence_confirm_note = QLineEdit()
        _form(box, (("整组复核 / 撤销依据", self.evidence_confirm_note),))
        self.evidence_confirm_button = _button(self, "确认整组证据链", self.confirm_evidence_selected)
        self.evidence_unconfirm_button = _button(self, "撤销整组确认", self.undo_evidence_confirmation_selected)
        _row(box, self.evidence_confirm_button, self.evidence_unconfirm_button, _button(self, "查看本组来源", self.evidence_source_detail))
        self.evidence_rows = []
        self.evidence_link_ids = []
        self.evidence_period.currentIndexChanged.connect(lambda *_: self.guard(self.render_evidence_report))
        self.evidence_group.currentIndexChanged.connect(lambda *_: self.guard(self._render_evidence_group))
        self.evidence_doc.currentIndexChanged.connect(lambda *_: self.guard(self._evidence_banks))
        self.evidence_table.clicked.connect(lambda *_: self.guard(self.evidence_group_detail))
        self.evidence_link_table.clicked.connect(lambda *_: self.guard(self.evidence_link_detail))

    def render_evidence_report(self):
        report = evidence_report(self.workspace, period=self._audit_period(self.evidence_period))
        self.evidence_rows = report["groups"]
        _fill(self.evidence_table, ("单位", "业务编号", "方向", "合同限额（元）", "发票净额（元）", "凭证收付净额（元）", "银行证明净额（元）", "未关联证明（元）", "状态", "缺少凭证", "待核事项"), [[p["party"], p["business"], "应收" if p["direction"] == "receivable" else "应付", _money(p["limit_minor"]), _money(p["invoice_minor"]), _money(p["declared_paid_minor"]), _money(p["verified_paid_minor"]), _money(p["cash_unlinked_minor"]), p["status"], "、".join(p["missing"]), "；".join(p["flags"])] for p in self.evidence_rows], [p["id"] for p in self.evidence_rows])
        _options(self.evidence_group, [(f'{p["party"]} / {p["business"]} / {"应收" if p["direction"] == "receivable" else "应付"} / {p["status"]}', p["id"]) for p in self.evidence_rows])
        self._render_evidence_group()

    def _selected_evidence(self):
        return next((p for p in self.evidence_rows if p["id"] == self.evidence_group.currentData()), None)

    def _require_evidence(self):
        self._audit_require_current(self.evidence_period)
        p = self._selected_evidence()
        if p is None:
            fail("请先选择业务凭证组")
        return p

    def _render_evidence_group(self):
        p = self._selected_evidence()
        s = self.workspace.state
        editable = self._audit_editable(self.evidence_period) and p is not None
        rows = [self.workspace.records[rid] for rid in (p["rows"] if p else ()) if rid in self.workspace.records]
        rule = getattr(s, "evidence_rules", {}).get(p["id"], {}) if p and editable else {}
        signature = (self.evidence_period.currentData(), p["id"] if p else "", repr(rule))
        changed = signature != getattr(self, "_evidence_form_signature", None)
        _options(self.evidence_contract, [("未指定 / 单份合同可自动选择", "")] + [(self.label(r.id), r.id) for r in rows if r.extra.get("kind") == "合同"])
        if changed:
            for kind, checkbox in self.evidence_required.items():
                checkbox.setChecked(kind in rule.get("required", p.get("required", ()) if p else ()))
            self.evidence_rule_note.setText(rule.get("evidence", p.get("evidence", "") if p else ""))
            selected_contract = rule.get("contract", p.get("contract", "") if p else "")
            self.evidence_contract.setCurrentIndex(max(0, self.evidence_contract.findData(selected_contract)))
            self.evidence_confirm_note.setText(p.get("confirmation_evidence", "") if p else "")
        self._evidence_form_signature = signature
        _options(self.evidence_doc, [(self.label(r.id), r.id) for r in rows if r.extra.get("kind") in ("付款", "收款", "退款")])
        self._evidence_banks()
        for widget in (*self.evidence_required.values(), self.evidence_contract, self.evidence_rule_note, self.evidence_save_button, self.evidence_undo_rule_button, self.evidence_doc, self.evidence_cash, self.evidence_amount, self.evidence_cash_note, self.evidence_link_button, self.evidence_unlink_button, self.evidence_confirm_note, self.evidence_confirm_button, self.evidence_unconfirm_button):
            widget.setEnabled(editable)
        self.evidence_undo_rule_button.setEnabled(editable and bool(rule))
        self.evidence_unconfirm_button.setEnabled(editable and p["id"] in getattr(s, "evidence_confirmations", {}))
        details = self._audit_link_details(p, "evidence_cash_links")
        self._evidence_links = details
        self.evidence_link_ids = list(p.get("cash_links", ())) if p else []
        _fill(self.evidence_link_table, ("资金证明编号", "凭证", "银行流水", "关联（元）", "依据", "期间"), [[key, self.label(details[key]["document"]), self.label(details[key]["cash"]), _money(details[key]["amount_minor"]), details[key].get("evidence", ""), details[key].get("period", "")] if key in details else [key, "历史快照仅保存关联编号", "", "", "", ""] for key in self.evidence_link_ids], self.evidence_link_ids)
        self.evidence_status.setText((f'{p["period"]} / {"当前未结账" if editable else "只读快照"} / {p["status"]}\n待核事项：{"；".join(p["flags"]) or "无"}；规则依据：{p.get("evidence", "") or "未登记"}' if p else "暂无业务凭证。请导入合同、订单、收货、验收、发票及收付款凭证；历史仅显示已保存快照。"))

    def _audit_link_details(self, row, state_field):
        if row is None:
            return {}
        stored = row.get("cash_link_details")
        if isinstance(stored, dict):
            return stored
        selector = self.evidence_period if state_field == "evidence_cash_links" else self.contract_period
        return {} if self._audit_period(selector) is not None else getattr(self.workspace.state, state_field, {})

    def _evidence_banks(self):
        doc = self.workspace.records.get(self.evidence_doc.currentData())
        p = self._selected_evidence()
        positive = bool(p and p["direction"] == "receivable")
        if doc and doc.extra.get("kind") == "退款":
            positive = not positive
        _options(self.evidence_cash, [(self.label(r.id), r.id) for r in active_records(self.workspace).values() if doc and r.role == "bank" and r.amount_minor and (r.amount_minor > 0) == positive])

    def save_evidence_rule_selected(self):
        p = self._require_evidence()
        self.apply("register_evidence_rule", group=p["id"], required=[kind for kind, checkbox in self.evidence_required.items() if checkbox.isChecked()], contract=self.evidence_contract.currentData() or "", evidence=self.evidence_rule_note.text())

    def undo_evidence_rule_selected(self):
        p = self._require_evidence()
        self.apply("undo_evidence_rule", target=p["id"], note=self.evidence_rule_note.text())

    def link_evidence_cash_selected(self):
        self._require_evidence()
        self.apply("link_evidence_cash", document=self.evidence_doc.currentData(), cash=self.evidence_cash.currentData(), amount_minor=parse_amount(self.evidence_amount.text()), evidence=self.evidence_cash_note.text())

    def undo_evidence_cash_selected(self):
        self._require_evidence()
        self.apply("undo_evidence_cash", target=self._choose(self.evidence_link_table, self.evidence_link_ids), note=self.evidence_cash_note.text())

    def confirm_evidence_selected(self):
        p = self._require_evidence()
        self.apply("confirm_evidence_chain", group=p["id"], evidence=self.evidence_confirm_note.text())

    def undo_evidence_confirmation_selected(self):
        p = self._require_evidence()
        self.apply("undo_evidence_confirmation", target=p["id"], note=self.evidence_confirm_note.text())

    def evidence_group_detail(self):
        if self.evidence_rows:
            p = self._choose(self.evidence_table, self.evidence_rows)
            self.evidence_group.setCurrentIndex(self.evidence_group.findData(p["id"]))
            self.evidence_source_detail()

    def evidence_source_detail(self):
        p = self._selected_evidence()
        if p:
            self.show_records(tuple(p["rows"]), p["status"] + "；" + "；".join(p["flags"]))

    def evidence_link_detail(self):
        if self.evidence_link_ids:
            p = self._evidence_links.get(self._choose(self.evidence_link_table, self.evidence_link_ids))
            if p:
                self.show_records((p["document"], p["cash"]), p.get("evidence", ""))

    def _contract_page(self):
        box = self._audit_page("合同阶段与收付款计划")
        self.contract_period = self._combo()
        self.contract_source = self._combo()
        _row(box, QLabel("报告期间"), self.contract_period, QLabel("合同来源"), self.contract_source)
        self.contract_status = _note(box, "请先导入合同凭证。")
        _note(box, "阶段日期按人工登记的合同条件及核实凭证计算，仅作计划提醒。阶段资金关联保存银行证明，不生成付款、记账或原有应收应付核销。")
        self.stage_name = QLineEdit()
        self.stage_amount = QLineEdit()
        self.stage_trigger = QComboBox()
        self.stage_trigger.addItems(_TRIGGERS)
        self.stage_base = QDateEdit()
        self.stage_base.setCalendarPopup(True)
        self.stage_base.setDisplayFormat("yyyy-MM-dd")
        self.stage_base.setDateRange(QDate(1900, 1, 1), QDate(9999, 12, 31))
        self.stage_base.setDate(QDate.currentDate())
        self.stage_delay = QSpinBox()
        self.stage_delay.setRange(0, 36500)
        self.stage_note = QLineEdit()
        _form(box, (("阶段名称", self.stage_name), ("阶段金额（元）", self.stage_amount), ("触发条件", self.stage_trigger), ("自定基准日期（仅自定日期使用）", self.stage_base), ("延后天数", self.stage_delay), ("阶段登记 / 撤销依据", self.stage_note)))
        self.stage_add_button = _button(self, "登记合同阶段", self.add_contract_stage_selected)
        self.stage_undo_button = _button(self, "撤销所选阶段", self.undo_contract_stage_selected)
        _row(box, self.stage_add_button, self.stage_undo_button, _button(self, "查看合同来源", self.contract_source_detail))
        self.stage_table = _audit_table(box)
        self.stage_choice = self._combo()
        self.stage_condition_doc = self._combo()
        self.stage_condition_note = QLineEdit()
        _form(box, (("操作阶段", self.stage_choice), ("条件凭证（到货 / 验收 / 开票）", self.stage_condition_doc), ("条件核实 / 撤销依据", self.stage_condition_note)))
        self.stage_verify_button = _button(self, "确认条件凭证成立", self.verify_stage_selected)
        self.stage_unverify_button = _button(self, "撤销条件核实", self.undo_stage_condition_selected)
        _row(box, self.stage_verify_button, self.stage_unverify_button, _button(self, "查看阶段及条件来源", self.stage_source_detail))
        self.stage_cash = self._combo()
        self.stage_cash_amount = QLineEdit()
        self.stage_cash_kind = QComboBox()
        self.stage_cash_kind.addItems(("结算", "退回"))
        self.stage_cash_note = QLineEdit()
        _form(box, (("银行资金证明", self.stage_cash), ("关联金额（元）", self.stage_cash_amount), ("资金性质", self.stage_cash_kind), ("资金关联 / 撤销依据", self.stage_cash_note)))
        self.stage_link_button = _button(self, "关联阶段资金证明", self.link_stage_cash_selected)
        self.stage_unlink_button = _button(self, "撤销所选阶段资金证明", self.undo_stage_cash_selected)
        _row(box, self.stage_link_button, self.stage_unlink_button)
        self.stage_link_table = _audit_table(box)
        self.contract_rows = []
        self.stage_rows = []
        self.stage_link_ids = []
        self.contract_period.currentIndexChanged.connect(lambda *_: self.guard(self.render_contract_report))
        self.contract_source.currentIndexChanged.connect(lambda *_: self.guard(self._render_contract))
        self.stage_choice.currentIndexChanged.connect(lambda *_: self.guard(self._render_stage))
        self.stage_cash_kind.currentIndexChanged.connect(lambda *_: self.guard(self._stage_banks))
        self.stage_trigger.currentIndexChanged.connect(lambda *_: self._stage_base_enabled())
        self.stage_table.clicked.connect(lambda *_: self.guard(self.stage_detail))
        self.stage_link_table.clicked.connect(lambda *_: self.guard(self.stage_link_detail))

    def render_contract_report(self):
        result = contract_report(self.workspace, period=self._audit_period(self.contract_period))
        self.contract_rows = result["contracts"]
        self._all_stage_rows = result["stages"]
        _options(self.contract_source, [(f'{p["party"]} / {p["business"]} / {p["reference"]} / {_money(p["amount_minor"])} 元', p["contract"]) for p in self.contract_rows])
        self._render_contract()

    def _selected_contract(self):
        return next((p for p in self.contract_rows if p["contract"] == self.contract_source.currentData()), None)

    def _selected_stage(self):
        return next((p for p in self.stage_rows if p["id"] == self.stage_choice.currentData()), None)

    def _require_contract(self):
        self._audit_require_current(self.contract_period)
        p = self._selected_contract()
        if p is None:
            fail("请先选择合同")
        return p

    def _require_stage(self):
        self._require_contract()
        p = self._selected_stage()
        if p is None:
            fail("请先选择合同阶段")
        return p

    def _render_contract(self):
        p = self._selected_contract()
        editable = self._audit_editable(self.contract_period) and p is not None
        self.stage_rows = [stage for stage in getattr(self, "_all_stage_rows", ()) if p and stage["contract"] == p["contract"]]
        _fill(self.stage_table, ("阶段编号", "名称", "触发条件", "计划（元）", "银行证明净额（元）", "未结清（元）", "到期日", "逾期（天）", "状态", "条件凭证", "提示", "登记依据"), [[r["id"], r["name"], r["trigger"], _money(r["amount_minor"]), _money(r["paid_minor"]), _money(r["remaining_minor"]), r["due_day"] or "条件未核实", r["overdue_days"] if r["overdue_days"] is not None else "未确定", r["status"], r["condition_document"], "；".join(r["flags"]), r["evidence"]] for r in self.stage_rows], [r["id"] for r in self.stage_rows])
        _options(self.stage_choice, [(f'{r["name"]} / {r["status"]} / 未结清 {_money(r["remaining_minor"])} 元', r["id"]) for r in self.stage_rows])
        for control in (self.stage_name, self.stage_amount, self.stage_trigger, self.stage_delay, self.stage_note, self.stage_add_button):
            control.setEnabled(editable)
        self._stage_base_enabled()
        self._render_stage()
        self.contract_status.setText((f'{"当前未结账" if editable else "只读快照"} / {p["party"]} / {p["reference"]} · 合同 {_money(p["amount_minor"])} 元 · 已计划 {_money(p["planned_minor"])} 元 · 未计划 {_money(p["unplanned_minor"])} 元 · 阶段银行证明净额 {_money(p["paid_minor"])} 元 · 合同尚余 {_money(p["remaining_minor"])} 元\n提示：{"；".join(p["flags"]) or "无"}' if p else "暂无合同凭证；历史期间仅显示已保存快照。"))

    def _stage_base_enabled(self):
        self.stage_base.setEnabled(self._audit_editable(self.contract_period) and self._selected_contract() is not None and self.stage_trigger.currentText() == "自定日期")

    def _render_stage(self):
        p = self._selected_stage()
        editable = self._audit_editable(self.contract_period) and p is not None
        contract = self.workspace.records.get(p["contract"]) if p else None
        needed = {"到货": "收货", "验收": "验收", "开票": "发票", "质保届满": "验收"}.get(p["trigger"] if p else "")
        docs = [r for r in active_records(self.workspace).values() if contract and r.role == "business_evidence" and r.extra.get("kind") == needed and r.party == contract.party and r.extra.get("business") == contract.extra.get("business") and r.extra.get("direction") == contract.extra.get("direction") and r.day >= contract.day and (needed != "发票" or r.amount_minor > 0)]
        _options(self.stage_condition_doc, [(self.label(r.id), r.id) for r in docs])
        signature = (self.contract_period.currentData(), p["id"] if p else "", p.get("condition_document", "") if p else "", p.get("condition_evidence", "") if p else "")
        if signature != getattr(self, "_stage_form_signature", None):
            self.stage_condition_note.setText(p.get("condition_evidence", "") if p else "")
            if p and p["condition_document"]:
                self.stage_condition_doc.setCurrentIndex(self.stage_condition_doc.findData(p["condition_document"]))
        self._stage_form_signature = signature
        self.stage_choice.setEnabled(p is not None)
        for control in (self.stage_undo_button, self.stage_cash, self.stage_cash_amount, self.stage_cash_kind, self.stage_cash_note, self.stage_link_button, self.stage_unlink_button):
            control.setEnabled(editable)
        for control in (self.stage_condition_doc, self.stage_condition_note, self.stage_verify_button):
            control.setEnabled(editable and needed is not None)
        self.stage_unverify_button.setEnabled(editable and bool(p["condition_document"]))
        self._stage_banks()
        self._stage_links = self._audit_link_details(p, "stage_cash_links")
        self.stage_link_ids = list(p["links"]) if p else []
        _fill(self.stage_link_table, ("关联编号", "银行流水", "性质", "阶段结算有符号额（元）", "依据", "期间"), [[key, self.label(self._stage_links[key]["cash"]), self._stage_links[key].get("kind", ""), _money(self._stage_links[key]["amount_minor"]), self._stage_links[key].get("evidence", ""), self._stage_links[key].get("period", "")] if key in self._stage_links else [key, "历史快照仅保存关联编号", "", "", "", ""] for key in self.stage_link_ids], self.stage_link_ids)

    def _stage_banks(self):
        p = self._selected_stage()
        positive = bool(p and p["direction"] == "receivable")
        if self.stage_cash_kind.currentText() == "退回":
            positive = not positive
        _options(self.stage_cash, [(self.label(r.id), r.id) for r in active_records(self.workspace).values() if p and r.role == "bank" and r.amount_minor and (r.amount_minor > 0) == positive])

    def add_contract_stage_selected(self):
        p = self._require_contract()
        trigger = self.stage_trigger.currentText()
        self.apply("register_contract_stage", contract=p["contract"], name=self.stage_name.text(), amount_minor=parse_amount(self.stage_amount.text()), trigger=trigger, base_day=self.stage_base.date().toString("yyyy-MM-dd") if trigger == "自定日期" else "", delay_days=self.stage_delay.value(), evidence=self.stage_note.text())

    def verify_stage_selected(self):
        p = self._require_stage()
        self.apply("verify_stage_condition", stage=p["id"], document=self.stage_condition_doc.currentData(), evidence=self.stage_condition_note.text())

    def undo_stage_condition_selected(self):
        p = self._require_stage()
        self.apply("undo_stage_condition", target=p["id"], note=self.stage_condition_note.text())

    def link_stage_cash_selected(self):
        p = self._require_stage()
        self.apply("link_stage_cash", stage=p["id"], cash=self.stage_cash.currentData(), amount_minor=parse_amount(self.stage_cash_amount.text()), kind=self.stage_cash_kind.currentText(), evidence=self.stage_cash_note.text())

    def undo_stage_cash_selected(self):
        self._require_stage()
        self.apply("undo_stage_cash", target=self._choose(self.stage_link_table, self.stage_link_ids), note=self.stage_cash_note.text())

    def undo_contract_stage_selected(self):
        p = self._require_stage()
        self.apply("undo_contract_stage", target=p["id"], note=self.stage_note.text())

    def contract_source_detail(self):
        p = self._selected_contract()
        if p:
            self.show_records((p["contract"],), "；".join(p["flags"]))

    def stage_detail(self):
        if self.stage_rows:
            p = self._choose(self.stage_table, self.stage_rows)
            self.stage_choice.setCurrentIndex(self.stage_choice.findData(p["id"]))
            self.stage_source_detail()

    def stage_source_detail(self):
        p = self._selected_stage()
        if p:
            self.show_records(tuple(dict.fromkeys(rid for rid in (p["contract"], p["condition_document"], *p["cash_ids"]) if rid)), p["status"] + "；" + p.get("condition_evidence", "") + "；" + "；".join(p["flags"]))

    def stage_link_detail(self):
        if self.stage_link_ids:
            p = self._stage_links.get(self._choose(self.stage_link_table, self.stage_link_ids))
            if p:
                self.show_records((p["cash"],), p.get("evidence", ""))

    def _correction_page(self):
        box = self._audit_page("更正模拟与影响复核")
        _note(box, "先把拟更正动作加入队列，再模拟查看余额、账龄、资金和证据影响。模拟不修改工作区；应用时重新验证并一次保存全部动作。有关联退款等依赖时须明确追加撤销步骤，不会自动级联删除。已结账期间只读。")
        self.correction_reason = QLineEdit()
        self.correction_reason.setPlaceholderText("本次更正原因及核实依据；将保留在审计记录中")
        self.correction_mode = QComboBox()
        self.correction_mode.addItems(_MODES)
        self.correction_target = self._combo()
        self.correction_item = self._combo()
        self.correction_credit = self._combo()
        self.correction_amount = QLineEdit()
        self.correction_category = QComboBox()
        self.correction_category.addItems(CREDIT_CATEGORIES)
        _form(box, (("更正原因 / 依据", self.correction_reason), ("动作", self.correction_mode), ("原操作", self.correction_target), ("新应收 / 应付单据", self.correction_item), ("红字来源", self.correction_credit), ("新核销 / 抵减金额（元）", self.correction_amount), ("红字抵减类别", self.correction_category)))
        self.correction_add_button = _button(self, "加入更正队列", self.add_correction_step)
        self.correction_remove_button = _button(self, "移除最后一步", self.remove_correction_step)
        self.correction_clear_button = _button(self, "清空队列", self.clear_correction_steps)
        _row(box, self.correction_add_button, self.correction_remove_button, self.correction_clear_button)
        self.correction_ops = []
        self.correction_preview_data = None
        self._correction_generation = 0
        _note(box, "待模拟动作队列（按顺序执行）")
        self.correction_queue_table = _audit_table(box)
        self.correction_preview_button = _button(self, "模拟更正影响", self.preview_correction_selected)
        self.correction_apply_button = _button(self, "应用已复核的模拟方案", self.apply_correction_selected)
        self.correction_apply_button.setEnabled(False)
        _row(box, self.correction_preview_button, self.correction_apply_button)
        self.correction_status = _note(box, "尚未模拟；请填写原因并加入动作。")
        _note(box, "模拟影响明细（金额指标按元显示）")
        self.correction_table = _audit_table(box)
        _note(box, "已应用更正的审计历史（只读）")
        self.correction_history_table = _audit_table(box)
        self.correction_mode.currentIndexChanged.connect(lambda *_: self.guard(self._correction_targets))
        self.correction_target.currentIndexChanged.connect(lambda *_: self.guard(self._correction_items))
        self.correction_credit.currentIndexChanged.connect(lambda *_: self.guard(self._correction_items))
        self.correction_reason.textChanged.connect(lambda *_: self._invalidate_correction("原因已变化，请重新模拟"))

    def _invalidate_correction(self, message="队列已变化，请重新模拟"):
        self._correction_generation += 1
        self.correction_preview_data = None
        self.correction_apply_button.setEnabled(False)
        self.correction_status.setText(message)

    def _correction_targets(self):
        s = self.workspace.state
        mode = self.correction_mode.currentText()
        field = "allocations" if mode == "改核销单据" else _UNDOS.get(mode, ("", ""))[0]
        entries = []
        for key, p in getattr(s, field, {}).items():
            source = p.get("item") or p.get("cash") or p.get("outgoing") or p.get("document") or ""
            entries.append((f'{key} / {self.label(source) if source else ""} / {_money(p.get("amount_minor"))} 元', key))
        _options(self.correction_target, entries)
        credits = [r for r in active_records(self.workspace).values() if r.role in ("receivable_credit", "payable_credit")]
        _options(self.correction_credit, [(self.label(r.id), r.id) for r in credits])
        editable = self._audit_editable()
        self.correction_target.setEnabled(editable and mode != "红字抵减")
        self.correction_credit.setEnabled(editable and mode == "红字抵减")
        self.correction_category.setEnabled(editable and mode == "红字抵减")
        self.correction_amount.setEnabled(editable and mode in ("红字抵减", "改核销单据"))
        self._correction_items()

    def _correction_items(self):
        s = self.workspace.state
        mode = self.correction_mode.currentText()
        party = role = None
        if mode == "改核销单据":
            allocation = s.allocations.get(self.correction_target.currentData())
            cash = self.workspace.records.get(allocation["cash"]) if allocation else None
            if cash:
                party, role = cash.party, "receivable" if cash.amount_minor > 0 else "payable"
        elif mode == "红字抵减":
            credit = self.workspace.records.get(self.correction_credit.currentData())
            if credit:
                party, role = credit.party, {"receivable_credit": "receivable", "payable_credit": "payable"}.get(credit.role)
        _options(self.correction_item, [(self.label(r.id), r.id) for r in active_records(self.workspace).values() if role and r.role == role and r.party == party])
        self.correction_item.setEnabled(self._audit_editable() and mode in ("改核销单据", "红字抵减"))

    def add_correction_step(self):
        self._audit_require_current()
        reason = self.correction_reason.text().strip()
        if not reason:
            fail("请先填写更正原因及核实依据")
        mode = self.correction_mode.currentText()
        target = self.correction_target.currentData()
        if mode == "改核销单据":
            p = self.workspace.state.allocations.get(target)
            if p is None:
                fail("请选择要更正的原核销")
            item = self.correction_item.currentData()
            if not item:
                fail("请选择新的应收 / 应付单据")
            amount = parse_amount(self.correction_amount.text())
            if amount <= 0:
                fail("更正核销金额须为正数")
            data = {"item": item, "amount_minor": amount, "note": reason}
            if p.get("advance"):
                kind, data["advance"] = "allocate_advance", p["advance"]
            else:
                kind, data["cash"] = "allocate", p["cash"]
            ops = [{"kind": "undo_allocate", "data": {"target": target, "note": reason}}, {"kind": kind, "data": data}]
        elif mode == "红字抵减":
            credit, item = self.correction_credit.currentData(), self.correction_item.currentData()
            if not credit or not item:
                fail("请选择红字来源和抵减单据")
            amount = parse_amount(self.correction_amount.text())
            if amount <= 0:
                fail("抵减金额须为正数")
            ops = [{"kind": "apply_credit_note", "data": {"credit": credit, "item": item, "amount_minor": amount, "category": self.correction_category.currentText(), "evidence": reason}}]
        else:
            if not target:
                fail("请选择要撤销的原操作")
            ops = [{"kind": _UNDOS[mode][1], "data": {"target": target, "note": reason}}]
        if len(self.correction_ops) + len(ops) > 50:
            fail("更正队列最多50个事件；改核销占两个事件")
        self.correction_ops.extend(ops)
        self._invalidate_correction()
        self._render_correction_queue()

    def remove_correction_step(self):
        self._audit_require_current()
        if self.correction_ops:
            self.correction_ops.pop()
            self._invalidate_correction()
            self._render_correction_queue()

    def clear_correction_steps(self):
        self._audit_require_current()
        self.correction_ops.clear()
        self._invalidate_correction()
        self._render_correction_queue()

    def _render_correction_queue(self):
        _fill(self.correction_queue_table, ("顺序", "事件", "原操作 / 来源", "新单据", "金额（元）", "依据"), [[str(i + 1), p["kind"], p["data"].get("target") or p["data"].get("cash") or p["data"].get("advance") or p["data"].get("credit", ""), p["data"].get("item", ""), _money(p["data"].get("amount_minor")) if "amount_minor" in p["data"] else "", p["data"].get("note") or p["data"].get("evidence", "")] for i, p in enumerate(self.correction_ops)], [str(i) for i in range(len(self.correction_ops))])

    def preview_correction_selected(self):
        self._audit_require_current()
        if not self.correction_ops:
            fail("请先加入更正动作")
        reason = self.correction_reason.text().strip()
        if not reason:
            fail("请填写更正原因及依据")
        self._invalidate_correction("正在独立副本中模拟；工作区未改变")
        generation = self._correction_generation
        operations = deepcopy(self.correction_ops)
        workspace = deepcopy(self.workspace)
        base = corrections.workspace_fingerprint(self.workspace)
        def work(progress, cancelled):
            result = corrections.preview_correction(workspace, operations, reason, cancelled=cancelled)
            return result, cancelled()
        def done(payload):
            result, cancelled = payload
            if cancelled or generation != self._correction_generation:
                self.correction_apply_button.setEnabled(False)
                return
            if base != corrections.workspace_fingerprint(self.workspace) or operations != self.correction_ops or reason != self.correction_reason.text().strip():
                self._invalidate_correction("模拟期间工作区或方案已变化，请重新模拟")
                return
            self.correction_preview_data = result
            _fill(self.correction_table, ("影响区域", "对象", "指标", "更正前", "更正后"), [[p["area"], self.label(p["key"]) if p["key"] in self.workspace.records else p["key"], p["metric"], self._correction_value(p["metric"], p["before"]), self._correction_value(p["metric"], p["after"])] for p in result.get("changes", ())], [str(i) for i in range(len(result.get("changes", ())))])
            detail = "；".join(str(p) for p in result.get("blockers", ()))
            fresh = result.get("base") == corrections.workspace_fingerprint(self.workspace)
            self.correction_apply_button.setEnabled(bool(result.get("ok") and fresh and self._audit_editable()))
            self.status.setText("更正模拟完成；工作区未修改，请复核影响后应用" if result.get("ok") and fresh else "更正模拟未通过；请查看依赖或阻断说明")
            self.correction_status.setText((f'模拟成功：{len(operations)} 个事件，{len(result.get("changes", ()))} 项影响。请复核后应用；工作区尚未改变。' if result.get("ok") and fresh else "模拟不能应用：" + (result.get("error") or "工作区已变化")) + ("\n依赖 / 阻断：" + detail if detail else ""))
        self._run(work, done)

    @staticmethod
    def _correction_value(metric, value):
        if metric.endswith("_minor") and type(value) is int:
            return format_amount(value) + " 元"
        return "无" if value is None else str(value)

    def apply_correction_selected(self):
        self._audit_require_current()
        preview = self.correction_preview_data
        if not preview or not preview.get("ok"):
            fail("请先完成有效的更正模拟并复核影响")
        reason = self.correction_reason.text().strip()
        if preview.get("base") != corrections.workspace_fingerprint(self.workspace):
            self._invalidate_correction("工作区已变化，原模拟失效；请重新模拟")
            fail("工作区已变化，请重新模拟后再应用")
        if preview.get("operations") != self.correction_ops or preview.get("reason") != reason:
            self._invalidate_correction("模拟方案或原因已变化，请重新模拟")
            fail("模拟方案或原因已变化，请重新模拟")
        result = corrections.apply_correction(self.workspace, deepcopy(preview), reason)
        self._invalidate_correction("更正已应用并记录审计依据")
        self.correction_ops.clear()
        self.set_workspace(result)
        self.dirty = True
        self.status.setText("更正已应用并保留审计记录，请保存工作区")
        self.correction_status.setText("更正已应用；全部事件及更正原因已保存到当前工作区，请保存文件。")

    def _refresh_audit(self):
        s = self.workspace.state
        periods = [("当前期间 / " + s.period, "")] + [(p + " 月末快照（只读）", p) for p in sorted(s.closings)]
        _options(self.evidence_period, periods)
        _options(self.contract_period, periods)
        self.render_evidence_report()
        self.render_contract_report()
        self._correction_targets()
        self._render_correction_queue()
        editable = self._audit_editable()
        for control in (self.correction_reason, self.correction_mode, self.correction_add_button, self.correction_remove_button, self.correction_clear_button, self.correction_preview_button):
            control.setEnabled(editable)
        preview = self.correction_preview_data
        fresh = bool(preview and preview.get("base") == corrections.workspace_fingerprint(self.workspace) and preview.get("operations") == self.correction_ops and preview.get("reason") == self.correction_reason.text().strip())
        self.correction_apply_button.setEnabled(editable and fresh and bool(preview.get("ok")))
        if preview and not fresh:
            self._invalidate_correction("工作区或方案已变化，原模拟失效；队列保留，请重新模拟")
        if not editable:
            self.correction_status.setText("本期间已结账，只读；请进入下一未结账期间处理更正。")
        history = getattr(s, "corrections", {})
        entries = list(history.items()) if isinstance(history, dict) else [(str(i + 1), p) for i, p in enumerate(history)]
        _fill(self.correction_history_table, ("更正审计编号", "期间", "原因 / 依据", "动作数"), [[key, p.get("period", ""), p.get("reason", ""), len(p.get("operations", ()))] for key, p in entries], [key for key, _ in entries])
