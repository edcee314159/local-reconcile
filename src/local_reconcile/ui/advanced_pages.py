"""Net settlement proof and reviewed period recognition; all edits are events."""
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFormLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)
from .settlement_pages import _button, _row, _table, _populate, _options
from ..amounts import format_amount
from ..matching import stable_id
from ..domain import LocalReconcileError
from ..business.workspace import active_records, fail
from ..business.net_settlements import net_settlement_reports
from ..business.cutoff import cutoff_report


_METHODS = (("一次归属（业务当日）", "once"), ("按月平均归属", "monthly"), ("按日分摊归属", "daily"))
_ROLES = {"settlement_line": "结算组成", "settlement_order": "原订单", "bank": "银行流水",
          "cutoff_business": "业务确认基础", "cutoff_entry": "记账凭证"}
_SOURCE_HEADERS = ("来源类型", "记录编号", "单位", "日期", "金额（元）", "业务 / 凭证编号", "组成类别", "原订单", "摘要", "文件", "工作表", "来源行")


def _money(value, missing="未确认"):
    return missing if value is None else format_amount(value)


def _date_edit():
    widget = QDateEdit()
    widget.setCalendarPopup(True)
    widget.setDisplayFormat("yyyy-MM-dd")
    widget.setDateRange(QDate(1900, 1, 1), QDate(9999, 12, 31))
    widget.setDate(QDate.currentDate())
    return widget


def _fill_table(table, headers, rows, keys):
    """Preserve an explicitly selected source across model replacement."""
    selected = table.selectionModel().selectedRows() if table.selectionModel() else ()
    old_keys = getattr(table, "_advanced_keys", ())
    key = old_keys[selected[0].row()] if len(selected) == 1 and selected[0].row() < len(old_keys) else None
    _populate(table, headers, rows)
    table._advanced_keys = list(keys)
    if key is not None and key in table._advanced_keys:
        table.selectRow(table._advanced_keys.index(key))


class AdvancedPages:
    def _advanced_page(self, name):
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

    def _net_settlement_page(self):
        box = self._advanced_page("平台净到账核对")
        self.net_period = self._combo()
        self.net_group = self._combo()
        _row(box, QLabel("报告期间"), self.net_period, QLabel("平台 / 结算批次"), self.net_group)
        self.net_status = QLabel()
        self.net_status.setWordWrap(True)
        box.addWidget(self.net_status)
        self.net_table = _table(box)
        self.net_table.setMinimumHeight(95)
        self.net_table.setMaximumHeight(180)
        self.net_bank_list = QListWidget()
        self.net_bank_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.net_bank_list.setMinimumHeight(78)
        self.net_bank_list.setMaximumHeight(125)
        self.net_evidence = QLineEdit()
        self.net_evidence.setPlaceholderText("结算单、银行回单及退款 / 费用组成的核实依据")
        form = QFormLayout()
        form.addRow("银行流水（净额为零可留空）", self.net_bank_list)
        form.addRow("确认 / 撤销依据", self.net_evidence)
        box.addLayout(form)
        self.net_preview = QLabel()
        self.net_preview.setWordWrap(True)
        box.addWidget(self.net_preview)
        self.net_confirm_button = _button(self, "确认 / 重新复核净到账", self.confirm_net_selected)
        self.net_undo_button = _button(self, "撤销本组确认", self.undo_net_selected)
        self.net_exclude_button = _button(self, "凭依据排除所选来源行", self.exclude_net_source_selected)
        _row(box, self.net_confirm_button, self.net_undo_button, self.net_exclude_button)
        note = QLabel("按原订单、销售、退款、佣金、运费和其他加扣款重建净额；不推算费用。银行按有符号金额合计，须同一账户。净额为零且无资金往来可留空银行并注明依据。此确认保留结算证明，不生成记账或资金核销。选择下方来源行可查看原文件。")
        note.setWordWrap(True)
        box.addWidget(note)
        self.net_detail_tabs = QTabWidget()
        source_page = QWidget()
        self.net_source_table = _table(QVBoxLayout(source_page))
        self.net_source_table.setMinimumHeight(100)
        self.net_detail_tabs.addTab(source_page, "逐项组成 / 订单 / 银行来源")
        order_page = QWidget()
        self.net_order_table = _table(QVBoxLayout(order_page))
        self.net_detail_tabs.addTab(order_page, "原订单累计核查")
        box.addWidget(self.net_detail_tabs, 1)
        self.net_rows = []
        self.net_source_ids = []
        self.net_order_checks = []
        self.net_period.currentIndexChanged.connect(lambda *_: self.guard(self.render_net_settlements))
        self.net_group.currentIndexChanged.connect(lambda *_: self.guard(self._render_net_group))
        self.net_bank_list.itemSelectionChanged.connect(self._net_bank_preview)
        self.net_table.clicked.connect(lambda *_: self.guard(self.net_group_detail))
        self.net_source_table.clicked.connect(lambda *_: self.guard(self.net_source_detail))
        self.net_order_table.clicked.connect(lambda *_: self.guard(self.net_order_detail))

    def _cutoff_page(self):
        box = self._advanced_page("月末归属与跨期核对")
        self.cutoff_period = self._combo()
        self.cutoff_business = self._combo()
        _row(box, QLabel("报告期间"), self.cutoff_period, QLabel("业务 / 未关联凭证组"), self.cutoff_business)
        self.cutoff_status = QLabel()
        self.cutoff_status.setWordWrap(True)
        box.addWidget(self.cutoff_status)
        self.cutoff_table = _table(box)
        self.cutoff_table.setMinimumHeight(95)
        self.cutoff_table.setMaximumHeight(180)
        self.cutoff_method = QComboBox()
        for label, method in _METHODS:
            self.cutoff_method.addItem(label, method)
        self.cutoff_start = _date_edit()
        self.cutoff_end = _date_edit()
        self.cutoff_evidence = QLineEdit()
        self.cutoff_evidence.setPlaceholderText("验收、服务期间或财务已确认的归属基础及规则依据")
        form = QFormLayout()
        form.addRow("归属方法", self.cutoff_method)
        dates = QFormLayout()
        dates.addRow("开始日", self.cutoff_start)
        dates.addRow("结束日", self.cutoff_end)
        form.addRow("归属期间", dates)
        form.addRow("规则 / 撤销依据", self.cutoff_evidence)
        box.addLayout(form)
        self.cutoff_save_button = _button(self, "登记 / 更新归属规则", self.save_cutoff_rule_selected)
        self.cutoff_undo_button = _button(self, "撤销本业务规则", self.undo_cutoff_rule_selected)
        _row(box, self.cutoff_save_button, self.cutoff_undo_button)
        self.cutoff_explanation = QLineEdit()
        self.cutoff_explanation.setPlaceholderText("说明本期或前期差异，保留原差额并继续复核")
        self.cutoff_explain_button = _button(self, "保存差异说明", self.explain_cutoff_selected)
        self.cutoff_unexplain_button = _button(self, "撤销差异说明", self.undo_cutoff_explanation_selected)
        _row(box, QLabel("差异说明 / 撤销依据"), self.cutoff_explanation, self.cutoff_explain_button, self.cutoff_unexplain_button)
        note = QLabel("应归属金额以财务确认的业务基础和人工规则计算；实际金额仅取记账凭证。本期差异＝本期已记账－本期应归属，前期差异单独保留。发票、付款跨期仅提示，不据此生成分录；差异说明不会核平差额。")
        note.setWordWrap(True)
        box.addWidget(note)
        self.cutoff_source_table = _table(box)
        self.cutoff_source_table.setMinimumHeight(95)
        self.cutoff_exclude_button = _button(self, "凭规则依据排除所选来源行", self.exclude_cutoff_source_selected)
        box.addWidget(self.cutoff_exclude_button)
        self.cutoff_rows = []
        self.cutoff_source_ids = []
        self.cutoff_period.currentIndexChanged.connect(lambda *_: self.guard(self.render_cutoff_report))
        self.cutoff_business.currentIndexChanged.connect(lambda *_: self.guard(self._render_cutoff_business))
        self.cutoff_method.currentIndexChanged.connect(lambda *_: self._cutoff_method_changed())
        self.cutoff_table.clicked.connect(lambda *_: self.guard(self.cutoff_business_detail))
        self.cutoff_source_table.clicked.connect(lambda *_: self.guard(self.cutoff_source_detail))

    def _refresh_advanced(self):
        s = self.workspace.state
        periods = [("当前期间 / " + s.period, None)] + [(p + " 月末快照（只读）", p) for p in sorted(s.closings)]
        _options(self.net_period, periods)
        _options(self.cutoff_period, periods)
        self.render_net_settlements()
        self.render_cutoff_report()

    def _advanced_editable(self, selector):
        return selector.currentData() is None and self.workspace.state.period not in self.workspace.state.closings

    def _advanced_require_current(self, selector):
        if not self._advanced_editable(selector):
            fail("历史月末报告只读，请切换到当前未结账期间")

    def _advanced_sources(self, ids):
        batches = {b.id: b for b in self.workspace.batches}
        rows = []
        for rid in ids:
            r = self.workspace.records.get(rid)
            if r is None:
                rows.append(["来源记录未找到", rid])
                continue
            b = batches.get(r.batch_id)
            raw = next((x for x in b.raw.rows if x.id == r.source_id), None) if b else None
            extra = getattr(r, "extra", {})
            rows.append([_ROLES.get(r.role, r.role), rid, r.party, r.day, format_amount(r.amount_minor),
                         extra.get("entry") or r.reference, extra.get("category", ""), extra.get("order", ""),
                         r.summary, b.raw.filename if b else "", (b.raw.sheet or "CSV") if b else "",
                         raw.source_line if raw else ""])
        return rows

    def render_net_settlements(self):
        self._net_report_error = ""
        try:
            self.net_rows = net_settlement_reports(self.workspace, period=self.net_period.currentData())
        except LocalReconcileError as exc:
            self.net_rows = []
            self._net_report_error = str(exc)
        headers = ("平台 / 单位", "结算批次", "期间", "销售（元）", "退款（元）", "费用扣款（元）", "其他加款（元）", "净额（元）", "已确认银行（元）", "银行－净额（元）", "状态", "问题", "核实依据", "复核有效")
        _fill_table(self.net_table, headers,
                    [[p["party"], p["settlement"], p["period"], format_amount(p["income_minor"]),
                      format_amount(p["refund_minor"]), format_amount(p["fee_minor"]), format_amount(p["other_minor"]),
                      format_amount(p["net_minor"]), _money(p["bank_minor"]), _money(p["difference_minor"]),
                      p["status"], "；".join(p["issues"]), p["evidence"], "是" if p["review_valid"] else "否"] for p in self.net_rows],
                    [p["id"] for p in self.net_rows])
        _options(self.net_group, [(p["party"] + " / " + p["settlement"] + " / " + p["status"], p["id"]) for p in self.net_rows])
        self._render_net_group()

    def _selected_net_group(self):
        group = self.net_group.currentData()
        return next((p for p in self.net_rows if p["id"] == group), None)

    def _render_net_group(self):
        p = self._selected_net_group()
        editable = self._advanced_editable(self.net_period) and p is not None
        for control in (self.net_bank_list, self.net_evidence, self.net_confirm_button, self.net_exclude_button):
            control.setEnabled(editable)
        self.net_undo_button.setEnabled(editable and p["id"] in self.workspace.state.net_settlements)
        self.net_source_ids = list(dict.fromkeys((*p["rows"], *p["orders"], *p["banks"]))) if p else []
        _fill_table(self.net_source_table, _SOURCE_HEADERS, self._advanced_sources(self.net_source_ids), self.net_source_ids)
        self.net_order_checks = p.get("order_checks", []) if p else []
        _fill_table(self.net_order_table, ("原订单编号", "订单金额（元）", "累计销售结算（元）", "累计退款（元）", "尚未结算（元）", "来源记录"),
                    [[c["reference"], _money(c["order_minor"], "原订单缺失"), format_amount(c["settled_minor"]),
                      format_amount(c["refunded_minor"]), _money(c["remaining_minor"], "原订单缺失"), c["record"]]
                     for c in self.net_order_checks], [c["reference"] for c in self.net_order_checks])
        signature = (self.net_period.currentData(), p["id"], p["evidence"], tuple(p["banks"])) if p else None
        changed = signature != getattr(self, "_net_form_signature", None)
        selected = set(p["banks"] if p else ()) if changed else {i.data(Qt.UserRole) for i in self.net_bank_list.selectedItems()}
        if changed:
            self.net_evidence.setText(p["evidence"] if p else "")
        self._net_form_signature = signature
        self.net_bank_list.blockSignals(True)
        self.net_bank_list.clear()
        banks = [r for r in active_records(self.workspace).values() if r.role == "bank"] if editable else [self.workspace.records[rid] for rid in (p["banks"] if p else ()) if rid in self.workspace.records]
        occupied = {rid for other in self.net_rows if p and other["id"] != p["id"] for rid in other["banks"]}
        for r in banks:
            item = QListWidgetItem(f'{r.account} / {r.day} / {format_amount(r.amount_minor)} 元 / {r.party} / {r.reference} / {r.id}')
            item.setData(Qt.UserRole, r.id)
            self.net_bank_list.addItem(item)
            if r.id in occupied:
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                item.setToolTip("已被其他结算组确认占用，须先撤销该组确认")
            elif r.id in selected:
                item.setSelected(True)
        self.net_bank_list.blockSignals(False)
        if p:
            mode = "当前未结账" if self._advanced_editable(self.net_period) else "只读快照"
            issues = "；".join(p["issues"]) or "无组成 / 订单问题"
            self.net_status.setText(f'{p["period"]} / {mode} / {p["status"]} · 销售 {format_amount(p["income_minor"])}－退款 {format_amount(p["refund_minor"])}－费用 {format_amount(p["fee_minor"])}＋其他加款 {format_amount(p["other_minor"])}＝净额 {format_amount(p["net_minor"])} 元\n问题：{issues}；已确认银行－净额：{_money(p["difference_minor"])} 元；核实依据：{p["evidence"] or "未提供"}')
        else:
            self.net_status.setText(self._net_report_error or "暂无平台结算组成。请导入原订单和结算明细；历史期间仅展示当时保存的快照。")
        self._net_bank_preview()

    def _net_bank_preview(self):
        p = self._selected_net_group()
        if p is None:
            self.net_preview.setText("尚未选择结算组")
            return
        records = [self.workspace.records[i.data(Qt.UserRole)] for i in self.net_bank_list.selectedItems() if i.data(Qt.UserRole) in self.workspace.records]
        total = sum(r.amount_minor for r in records)
        warning = "；跨账户，不能确认" if len({r.account for r in records}) > 1 else ""
        if len(records) > 100:
            warning += "；超过100笔，不能确认"
        self.net_preview.setText(f'选中 {len(records)} 笔 · 银行有符号合计 {format_amount(total)} 元 · 结算净额 {format_amount(p["net_minor"])} 元 · 银行－净额 {format_amount(total - p["net_minor"])} 元{warning}')

    def confirm_net_selected(self):
        self._advanced_require_current(self.net_period)
        p = self._selected_net_group()
        if p is None:
            fail("请先选择结算组")
        banks = [item.data(Qt.UserRole) for item in self.net_bank_list.selectedItems()]
        if not (1 <= len(banks) <= 100 or not banks and p["net_minor"]==0):
            fail("请选择1—100笔银行流水；净额为零且无资金往来时可留空")
        self.apply("confirm_net_settlement", group=p["id"], banks=banks, evidence=self.net_evidence.text())

    def undo_net_selected(self):
        self._advanced_require_current(self.net_period)
        p = self._selected_net_group()
        if p is None or p["id"] not in self.workspace.state.net_settlements:
            fail("所选结算组尚无确认可撤销")
        self.apply("undo_net_settlement", target=p["id"], note=self.net_evidence.text())

    def net_group_detail(self):
        if not self.net_rows:
            return
        p = self._choose(self.net_table, self.net_rows)
        self.net_group.setCurrentIndex(self.net_group.findData(p["id"]))
        self.show_records(tuple(self.net_source_ids), p["status"] + "；" + "；".join(p["issues"]) + "；核实依据：" + p["evidence"])

    def net_order_detail(self):
        if not self.net_order_checks:
            return
        row = self._choose(self.net_order_table, self.net_order_checks)
        ids = (row["record"],) if row["record"] else ()
        self.show_records(ids, "原订单累计核查：" + row["reference"] + "；跨所有结算批次累计销售、退款。" + ("" if ids else "原订单缺失，须补充依据。"))

    def net_source_detail(self):
        if self.net_source_ids:
            self.show_records((self._choose(self.net_source_table, self.net_source_ids),))

    def exclude_net_source_selected(self):
        self._advanced_require_current(self.net_period)
        rid = self._choose(self.net_source_table, self.net_source_ids)
        self.apply("exclude", row=rid, note=self.net_evidence.text())

    @staticmethod
    def _cutoff_key(row):
        return row["business"] or stable_id("unmatched-cutoff", row["party"], row["reference"])

    def render_cutoff_report(self):
        self._cutoff_report_error = ""
        try:
            report = cutoff_report(self.workspace, period=self.cutoff_period.currentData())
            self.cutoff_rows = report["rows"]
        except LocalReconcileError as exc:
            self.cutoff_rows = []
            self._cutoff_report_error = str(exc)
        headers = ("单位", "业务编号", "归属方法", "开始日", "结束日", "本期应归属（元）", "本期已记账（元）", "本期差异（元）", "前期累计差异（元）", "状态", "提示", "规则依据", "差异说明", "说明有效", "开票日", "付款日")
        _fill_table(self.cutoff_table, headers,
                    [[p["party"], p["reference"], dict((v, k) for k, v in _METHODS).get(p["method"], "未确认"),
                      p["start"], p["end"], _money(p["expected_minor"]), format_amount(p["actual_minor"]),
                      _money(p["delta_minor"]), _money(p["prior_delta_minor"]), p["status"], "；".join(p["flags"]),
                      p["evidence"], p["explanation"], "是" if p["explanation_valid"] else "否", p["invoice_day"] or "未提供", p["payment_day"] or "未提供"] for p in self.cutoff_rows],
                    [self._cutoff_key(p) for p in self.cutoff_rows])
        _options(self.cutoff_business, [(f'{p["party"]} / {p["reference"]} / {p["status"]}', self._cutoff_key(p)) for p in self.cutoff_rows])
        self._render_cutoff_business()

    def _selected_cutoff_business(self):
        key = self.cutoff_business.currentData()
        return next((p for p in self.cutoff_rows if self._cutoff_key(p) == key), None)

    def _render_cutoff_business(self):
        p = self._selected_cutoff_business()
        r = self.workspace.records.get(p["business"]) if p else None
        editable = self._advanced_editable(self.cutoff_period) and bool(p and p["business"] and r)
        self._cutoff_form_editable = editable
        signature = ((self.cutoff_period.currentData(), self._cutoff_key(p), p["method"], str(p["start"]),
                      str(p["end"]), p["evidence"], p["explanation"]) if p else None)
        if signature != getattr(self, "_cutoff_form_signature", None):
            self.cutoff_method.blockSignals(True)
            self.cutoff_method.setCurrentIndex(max(0, self.cutoff_method.findData(p["method"] if p else "once")))
            self.cutoff_method.blockSignals(False)
            for widget, key in ((self.cutoff_start, "start"), (self.cutoff_end, "end")):
                value = str(p[key]) if p and p[key] else str(r.day) if r else (self.cutoff_period.currentData() or self.workspace.state.period) + "-01"
                value_date = QDate.fromString(value, "yyyy-MM-dd")
                if value_date.isValid():
                    widget.setDate(value_date)
            self.cutoff_evidence.setText(p["evidence"] if p else "")
            self.cutoff_explanation.setText(p["explanation"] if p else "")
        self._cutoff_form_signature = signature
        for control in (self.cutoff_method, self.cutoff_evidence, self.cutoff_save_button):
            control.setEnabled(editable)
        has_rule = bool(p and p["method"])
        has_explanation = bool(p and p["explanation"])
        self.cutoff_undo_button.setEnabled(editable and has_rule and not has_explanation)
        self.cutoff_explanation.setEnabled(editable and has_rule)
        self.cutoff_explain_button.setEnabled(editable and has_rule)
        self.cutoff_unexplain_button.setEnabled(editable and has_explanation)
        self.cutoff_exclude_button.setEnabled(self._advanced_editable(self.cutoff_period) and p is not None)
        self._cutoff_method_changed()
        self.cutoff_source_ids = list(dict.fromkeys(([p["business"]] if p and p["business"] else []) + list(p["entries"] if p else ())))
        _fill_table(self.cutoff_source_table, _SOURCE_HEADERS, self._advanced_sources(self.cutoff_source_ids), self.cutoff_source_ids)
        if p:
            mode = "当前未结账" if self._advanced_editable(self.cutoff_period) else "只读快照"
            self.cutoff_status.setText(f'{self.cutoff_period.currentData() or self.workspace.state.period} / {mode} / {p["status"]} · 本期应归属 {_money(p["expected_minor"])} 元 · 本期已记账 {format_amount(p["actual_minor"])} 元 · 本期差异 {_money(p["delta_minor"])} 元 · 前期累计差异 {_money(p["prior_delta_minor"])} 元\n提示：{"；".join(p["flags"]) or "无"}；规则依据：{p["evidence"] or "未提供"}；差异说明：{p["explanation"] or "未提供"}')
        else:
            self.cutoff_status.setText(self._cutoff_report_error or "暂无业务或记账凭证。请导入财务已确认的业务基础及记账记录；归属规则须人工确认，历史期间仅展示当时快照。")

    def _cutoff_method_changed(self):
        p = self._selected_cutoff_business()
        once = self.cutoff_method.currentData() == "once"
        r = self.workspace.records.get(p["business"]) if p else None
        if once and r:
            day = QDate.fromString(str(r.day), "yyyy-MM-dd")
            self.cutoff_start.setDate(day)
            self.cutoff_end.setDate(day)
        for widget in (self.cutoff_start, self.cutoff_end):
            widget.setEnabled(getattr(self, "_cutoff_form_editable", False) and not once)

    def _editable_cutoff_business(self, require_rule=False):
        self._advanced_require_current(self.cutoff_period)
        p = self._selected_cutoff_business()
        if p is None or not p["business"]:
            fail("请选择已关联业务；未关联记账记录不能登记规则或差异说明")
        if require_rule and not p["method"]:
            fail("请先确认业务归属规则")
        return p

    def save_cutoff_rule_selected(self):
        p = self._editable_cutoff_business()
        self._cutoff_method_changed()
        self.apply("register_cutoff_rule", business=p["business"], method=self.cutoff_method.currentData(),
                   start=self.cutoff_start.date().toString("yyyy-MM-dd"), end=self.cutoff_end.date().toString("yyyy-MM-dd"), evidence=self.cutoff_evidence.text())

    def undo_cutoff_rule_selected(self):
        p = self._editable_cutoff_business(require_rule=True)
        self.apply("undo_cutoff_rule", target=p["business"], note=self.cutoff_evidence.text())

    def explain_cutoff_selected(self):
        p = self._editable_cutoff_business(require_rule=True)
        self.apply("explain_cutoff", business=p["business"], evidence=self.cutoff_explanation.text())

    def undo_cutoff_explanation_selected(self):
        p = self._editable_cutoff_business(require_rule=True)
        self.apply("undo_cutoff_explanation", target=p["business"], note=self.cutoff_explanation.text())

    def cutoff_business_detail(self):
        if not self.cutoff_rows:
            return
        p = self._choose(self.cutoff_table, self.cutoff_rows)
        self.cutoff_business.setCurrentIndex(self.cutoff_business.findData(self._cutoff_key(p)))
        self.show_records(tuple(self.cutoff_source_ids), p["status"] + "；规则依据：" + p["evidence"] + "；差异说明：" + p["explanation"] + "；" + "；".join(p["flags"]))

    def cutoff_source_detail(self):
        if self.cutoff_source_ids:
            self.show_records((self._choose(self.cutoff_source_table, self.cutoff_source_ids),))

    def exclude_cutoff_source_selected(self):
        self._advanced_require_current(self.cutoff_period)
        rid = self._choose(self.cutoff_source_table, self.cutoff_source_ids)
        self.apply("exclude", row=rid, note=self.cutoff_evidence.text())


