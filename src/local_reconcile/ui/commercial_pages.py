"""Credit-note, duplicate review and partner-statement pages."""
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QComboBox, QInputDialog
from .settlement_pages import _button, _row, _table, _populate, _options
from ..amounts import parse_amount, format_amount
from ..domain import LocalReconcileError
from ..business.workspace import active_records, period_end, fail
from ..business.settlements import item_used
from ..business.credits import credit_rows, CREDIT_ROLES, CREDIT_CATEGORIES
from ..business.duplicates import duplicate_groups
from ..business.counterparty import counterparty_report, PARTNER_ROLES

_NAMES = {"receivable": "应收", "payable": "应付", "receivable_credit": "应收红字", "payable_credit": "应付红字"}


class CommercialPages:
    def _credit_page(self):
        box = self._page("红字与退货折让")
        self.credit_source = self._combo()
        self.credit_item = self._combo()
        self.credit_category = QComboBox()
        self.credit_category.addItems(CREDIT_CATEGORIES)
        self.credit_amount = QLineEdit()
        self.credit_evidence = QLineEdit()
        self.credit_evidence.setPlaceholderText("填写红字单据、退货或折让依据")
        form = QFormLayout()
        for label, widget in (("红字 / 退货 / 折让来源", self.credit_source), ("抵减原单据", self.credit_item), ("类别", self.credit_category), ("本次抵减（元）", self.credit_amount), ("核实依据", self.credit_evidence)):
            form.addRow(label, widget)
        box.addLayout(form)
        self.credit_apply_button = _button(self, "确认本次抵减", self.apply_credit_selected)
        self.credit_undo_button = _button(self, "撤销所选抵减", self.undo_credit_selected)
        _row(box, self.credit_apply_button, self.credit_undo_button)
        note = QLabel("抵减同一单位、对应应收应付方向的未结清单据，支持分次使用。实际退款请在“退款与冲销”页关联银行流水。")
        note.setWordWrap(True)
        box.addWidget(note)
        self.credit_source_table = _table(box)
        self.credit_table = _table(box)
        self.credit_source.currentIndexChanged.connect(lambda *_: self.guard(self._credit_targets))
        self.credit_source_table.clicked.connect(lambda *_: self.guard(self.credit_source_detail))
        self.credit_table.clicked.connect(lambda *_: self.guard(self.credit_detail))

    def _duplicate_page(self):
        box = self._page("重复记录复核")
        note = QLabel("系统列出不同批次中疑似重复的银行及账面记录。核实后可凭依据确认整组均为独立业务，或选中确属重复的一行排除。")
        note.setWordWrap(True)
        box.addWidget(note)
        self.duplicate_status = QLabel()
        box.addWidget(self.duplicate_status)
        self.duplicate_evidence = QLineEdit()
        self.duplicate_evidence.setPlaceholderText("填写独立业务或排除该来源行的核实依据")
        _row(box, QLabel("核实依据"), self.duplicate_evidence)
        self.duplicate_review_button = _button(self, "确认整组均为独立业务", self.review_duplicate_selected)
        self.duplicate_exclude_button = _button(self, "排除所选来源行", self.exclude_duplicate_selected)
        _row(box, self.duplicate_review_button, self.duplicate_exclude_button)
        self.duplicate_table = _table(box)
        self.duplicate_member_table = _table(box)
        self.duplicate_table.clicked.connect(lambda *_: self.guard(self.render_duplicate_members))
        self.duplicate_member_table.clicked.connect(lambda *_: self.guard(self.duplicate_member_detail))

    def _partner_page(self):
        box = self._page("客户供应商对账")
        self.partner_period = self._combo()
        self.partner_batch = self._combo()
        _row(box, QLabel("报告期间"), self.partner_period, QLabel("对方对账单"), self.partner_batch)
        self.partner_as_of = QLineEdit()
        self.partner_as_of.setPlaceholderText("YYYY-MM-DD，本期月末")
        self.partner_statement_evidence = QLineEdit()
        self.partner_statement_evidence.setPlaceholderText("对账单签收、盖章或其他来源依据")
        form = QFormLayout()
        form.addRow("对账单截止日", self.partner_as_of)
        form.addRow("对账单依据", self.partner_statement_evidence)
        box.addLayout(form)
        self.partner_register_button = _button(self, "登记 / 更新对账单依据", self.register_partner_selected)
        box.addWidget(self.partner_register_button)
        self.partner_status = QLabel()
        self.partner_status.setWordWrap(True)
        box.addWidget(self.partner_status)
        self.partner_table = _table(box)
        self.partner_decision_evidence = QLineEdit()
        self.partner_decision_evidence.setPlaceholderText("填写本笔确认或差异说明的核实依据")
        _row(box, QLabel("本笔核实依据"), self.partner_decision_evidence)
        self.partner_confirm_button = _button(self, "确认所选金额一致", lambda: self.decide_partner_selected("confirmed"))
        self.partner_explain_button = _button(self, "登记所选差异说明", lambda: self.decide_partner_selected("explained"))
        self.partner_undo_button = _button(self, "撤销所选确认 / 说明", self.undo_partner_selected)
        _row(box, self.partner_confirm_button, self.partner_explain_button, self.partner_undo_button)
        note = QLabel("按往来单位与单据编号逐笔比较本企业未结清余额和对方余额。差异说明保留差额；后续核销、退款或红字抵减使余额变化后需重新复核。缺单以“缺失”显示。")
        note.setWordWrap(True)
        box.addWidget(note)
        self.partner_period.currentIndexChanged.connect(lambda *_: self.guard(self._partner_batches))
        self.partner_batch.currentIndexChanged.connect(lambda *_: self.guard(self.render_partner_report))
        self.partner_table.clicked.connect(lambda *_: self.guard(self.partner_detail))

    def _refresh_commercial(self):
        w = self.workspace
        s = w.state
        editable = s.period not in s.closings
        self.credit_rows = credit_rows(w)
        self.credit_source_ids = [p["id"] for p in self.credit_rows]
        _options(self.credit_source, [(f'{self.label(p["id"])} / 可用 {format_amount(p["remaining_minor"])}', p["id"]) for p in self.credit_rows if p["remaining_minor"] > 0])
        self._credit_targets()
        _populate(self.credit_source_table, ("类型", "单位", "红字编号", "原金额（元）", "已抵减（元）", "可用（元）"), [[_NAMES[p["role"]], p["party"], p["reference"], format_amount(p["amount_minor"]), format_amount(p["applied_minor"]), format_amount(p["remaining_minor"])] for p in self.credit_rows])
        self.credit_ids = list(s.credits)
        _populate(self.credit_table, ("操作编号", "红字来源", "原单据", "类别", "抵减（元）", "依据", "期间"), [[key, self.label(p["credit"]), self.label(p["item"]), p["category"], format_amount(p["amount_minor"]), p["evidence"], p["period"]] for key, p in s.credits.items()])
        for control in (self.credit_source, self.credit_item, self.credit_category, self.credit_amount, self.credit_evidence, self.credit_apply_button, self.credit_undo_button):
            control.setEnabled(editable)
        self.duplicate_groups = duplicate_groups(w)
        _populate(self.duplicate_table, ("状态", "组编号", "来源行数", "疑似重复依据", "复核依据"), [[p["status"], p["id"], len(p["rows"]), p["basis"], p["evidence"]] for p in self.duplicate_groups])
        self.duplicate_status.setText(f'{len(self.duplicate_groups)} 组疑似重复 · {sum(p["status"] == "待复核" for p in self.duplicate_groups)} 组待复核')
        self.duplicate_member_ids = []
        _populate(self.duplicate_member_table, ("来源记录", "文件", "工作表", "来源行"), [])
        for control in (self.duplicate_evidence, self.duplicate_review_button, self.duplicate_exclude_button):
            control.setEnabled(editable)
        periods = [("当前期间 / " + s.period, None)] + [(p + " 月末快照", p) for p in sorted(s.closings)]
        _options(self.partner_period, periods)
        self._partner_batches()

    def _credit_targets(self):
        w = self.workspace
        credit = w.records.get(self.credit_source.currentData())
        rows = [r for r in active_records(w).values() if credit and r.role == CREDIT_ROLES.get(credit.role) and r.party == credit.party and r.day <= credit.day and r.amount_minor - item_used(w.state, r.id) > 0]
        _options(self.credit_item, [(f'{self.label(r.id)} / 未结清 {format_amount(r.amount_minor-item_used(w.state,r.id))}', r.id) for r in rows])

    def apply_credit_selected(self):
        self.apply("apply_credit_note", credit=self.credit_source.currentData(), item=self.credit_item.currentData(), amount_minor=parse_amount(self.credit_amount.text()), category=self.credit_category.currentText(), evidence=self.credit_evidence.text())

    def undo_credit_selected(self):
        target = self._choose(self.credit_table, self.credit_ids)
        note, ok = QInputDialog.getText(self, "撤销红字抵减", "请填写撤销依据：")
        if ok:
            self.apply("undo_credit_note", target=target, note=note)

    def credit_source_detail(self):
        self.show_records((self._choose(self.credit_source_table, self.credit_source_ids),))

    def credit_detail(self):
        p = self.workspace.state.credits[self._choose(self.credit_table, self.credit_ids)]
        self.show_records((p["credit"], p["item"]), p["category"] + "依据：" + p["evidence"])

    def render_duplicate_members(self):
        group = self._choose(self.duplicate_table, self.duplicate_groups)
        self.duplicate_member_ids = list(group["rows"])
        rows = []
        for rid in self.duplicate_member_ids:
            r = self.workspace.records[rid]
            batch = next(b for b in self.workspace.batches if b.id == r.batch_id)
            raw = next(row for row in batch.raw.rows if row.id == r.source_id)
            rows.append([self.label(rid), batch.raw.filename, batch.raw.sheet or "CSV", raw.source_line])
        _populate(self.duplicate_member_table, ("来源记录", "文件", "工作表", "来源行"), rows)
        self.show_records(tuple(self.duplicate_member_ids), group["basis"] + "；" + group["evidence"])

    def review_duplicate_selected(self):
        group = self._choose(self.duplicate_table, self.duplicate_groups)
        self.apply("review_duplicate", group=group["id"], evidence=self.duplicate_evidence.text())

    def exclude_duplicate_selected(self):
        rid = self._choose(self.duplicate_member_table, self.duplicate_member_ids)
        self.apply("exclude", row=rid, note=self.duplicate_evidence.text())

    def duplicate_member_detail(self):
        self.show_records((self._choose(self.duplicate_member_table, self.duplicate_member_ids),))

    def _partner_batches(self):
        w = self.workspace
        period = self.partner_period.currentData()
        stored = w.state.closings.get(period or w.state.period)
        available = set(stored.get("partner_reports", {})) if stored is not None else None
        entries = []
        for b in w.batches:
            if b.role not in PARTNER_ROLES or (available is not None and b.id not in available):
                continue
            statement = w.state.partner_statements.get(b.id)
            parties = sorted({r.party for r in w.records.values() if r.batch_id == b.id})
            label = f'{" / ".join(parties)} / {b.raw.filename} / {statement["as_of"] if statement else "未登记截止日"}'
            entries.append((label, b.id))
        _options(self.partner_batch, entries)
        self.render_partner_report()

    def render_partner_report(self):
        w = self.workspace
        s = w.state
        period = self.partner_period.currentData()
        bid = self.partner_batch.currentData()
        editable = period is None and s.period not in s.closings and bid is not None
        for control in (self.partner_as_of, self.partner_statement_evidence, self.partner_register_button, self.partner_decision_evidence, self.partner_confirm_button, self.partner_explain_button, self.partner_undo_button):
            control.setEnabled(editable)
        self.partner_rows = []
        headers = ("单据编号", "本企业未结清（元）", "对方余额（元）", "差额（元）", "状态", "核实依据")
        _populate(self.partner_table, headers, [])
        statement = s.partner_statements.get(bid)
        self.partner_as_of.setText(statement["as_of"] if statement else period_end(s.period).isoformat())
        self.partner_statement_evidence.setText(statement["evidence"] if statement else "")
        if bid is None:
            self.partner_status.setText("请先导入客户或供应商对账单。所选历史期间仅列出已保存快照的对账单。")
            return
        try:
            result = counterparty_report(w, bid, period=period)
        except LocalReconcileError as exc:
            self.partner_status.setText(str(exc))
            for control in (self.partner_decision_evidence, self.partner_confirm_button, self.partner_explain_button, self.partner_undo_button):
                control.setEnabled(False)
            return
        self.partner_rows = result["rows"]
        self.partner_status.setText(f'{result["period"]} / {result["party"]} / {_NAMES[result["role"]]} · 本企业 {format_amount(result["own_total_minor"])} 元 · 对方 {format_amount(result["partner_total_minor"])} 元 · 差额 {format_amount(result["difference_minor"])} 元')
        _populate(self.partner_table, headers, [[p["reference"], format_amount(p["own_minor"]) if p["own_minor"] is not None else "缺失", format_amount(p["partner_minor"]) if p["partner_minor"] is not None else "缺失", format_amount(p["difference_minor"]), p["status"], p["evidence"]] for p in self.partner_rows])

    def register_partner_selected(self):
        self.apply("register_partner_statement", batch=self.partner_batch.currentData(), as_of=self.partner_as_of.text().strip(), evidence=self.partner_statement_evidence.text())

    def _editable_partner_row(self):
        if self.partner_period.currentData() is not None or self.workspace.state.period in self.workspace.state.closings:
            fail("历史月末对账报告只读，请切换到当前未结账期间")
        return self._choose(self.partner_table, self.partner_rows)

    def decide_partner_selected(self, decision_kind):
        p = self._editable_partner_row()
        self.apply("decide_partner", batch=self.partner_batch.currentData(), own=p["own"], partner=p["partner"], kind=decision_kind, evidence=self.partner_decision_evidence.text())

    def undo_partner_selected(self):
        p = self._editable_partner_row()
        note, ok = QInputDialog.getText(self, "撤销对账核实", "请填写撤销确认或差异说明的依据：")
        if ok:
            self.apply("undo_partner_decision", target=p["id"], note=note)

    def partner_detail(self):
        p = self._choose(self.partner_table, self.partner_rows)
        self.show_records(tuple(rid for rid in (p["own"], p["partner"]) if rid), p["status"] + "；" + p["evidence"])
