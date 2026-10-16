"""Refund and advance pages sharing the validated business event API."""
from PySide6.QtWidgets import QFormLayout,QLineEdit,QComboBox,QLabel,QPushButton,QHBoxLayout,QTableView,QAbstractItemView
from .results_page import configure_table
from .table_models import DataTableModel
from ..amounts import parse_amount,format_amount
from ..business.workspace import active_records
from ..business.settlements import KINDS,advance_rows,allocation_net


def _button(owner,text,callback):
    b=QPushButton(text);b.clicked.connect(lambda checked=False:owner.guard(callback));return b


def _row(layout,*widgets):
    row=QHBoxLayout()
    for w in widgets:row.addWidget(w)
    layout.addLayout(row)


def _table(layout):
    t=QTableView();configure_table(t);t.setSelectionMode(QAbstractItemView.SingleSelection);layout.addWidget(t,1);return t


def _populate(t,headers,rows):
    t.setModel(DataTableModel(headers,rows,t));t.resizeColumnsToContents()


def _options(combo,entries):
    previous=combo.currentData();combo.blockSignals(True);combo.clear()
    for label,value in entries:combo.addItem(label,value)
    index=combo.findData(previous)
    if index>=0:combo.setCurrentIndex(index)
    combo.blockSignals(False)


class SettlementPages:
    def _refund_page(self):
        box=self._page("退款与冲销")
        self.refund_original=self._combo();self.refund_cash=self._combo();self.refund_target=self._combo()
        self.refund_category=QComboBox();self.refund_category.addItems(KINDS)
        self.refund_amount=QLineEdit();self.refund_evidence=QLineEdit()
        self.refund_evidence.setPlaceholderText("回单、退票通知或冲销依据；涉及不同往来单位时须说明关联关系")
        form=QFormLayout()
        for label,widget in (("原银行收付款",self.refund_original),("反方向银行流水",self.refund_cash),("恢复余额的来源",self.refund_target),("业务类别",self.refund_category),("本次金额（元）",self.refund_amount),("核实依据",self.refund_evidence)):form.addRow(label,widget)
        box.addLayout(form)
        _row(box,_button(self,"确认退款 / 冲销 / 退票",self.refund_selected),_button(self,"撤销所选退款",lambda:self.undo_table(self.refund_table,self.refund_ids,"undo_refund")))
        note=QLabel("根据实际反向流水关联原款项。已核销款项请选择原核销记录，系统恢复对应单据余额；未核销预收预付款请选择其登记。原始流水、旧期间快照均保留。")
        note.setWordWrap(True);box.addWidget(note);self.refund_table=_table(box)
        self.refund_table.clicked.connect(lambda *_:self.guard(self.refund_detail))
        self.refund_original.currentIndexChanged.connect(lambda *_:self._refund_targets())

    def _advance_page(self):
        box=self._page("预收预付款")
        self.advance_cash=self._combo();self.advance_amount=QLineEdit();self.advance_evidence=QLineEdit()
        form=QFormLayout();form.addRow("预收 / 预付银行流水",self.advance_cash);form.addRow("登记金额（元）",self.advance_amount);form.addRow("业务依据",self.advance_evidence);box.addLayout(form)
        _row(box,_button(self,"登记预收 / 预付款",self.register_advance_selected),_button(self,"撤销所选登记",lambda:self.undo_table(self.advance_table,self.advance_ids,"undo_advance")))
        self.advance_table=_table(box);self.advance_table.clicked.connect(lambda *_:self.guard(self.advance_detail))
        self.advance_combo=self._combo();self.advance_item=self._combo();self.advance_allocation_amount=QLineEdit();self.advance_note=QLineEdit()
        form=QFormLayout()
        for label,widget in (("使用预收 / 预付款",self.advance_combo),("后续应收 / 应付单据",self.advance_item),("本次核销（元）",self.advance_allocation_amount),("核实依据",self.advance_note)):form.addRow(label,widget)
        box.addLayout(form);_row(box,_button(self,"确认预收预付核销",self.allocate_advance_selected))
        note=QLabel("按同一往来单位及收付方向核销，支持分次使用余额。核销记录及撤销入口位于“应收应付核销”页；退款在“退款与冲销”页关联处理。")
        note.setWordWrap(True);box.addWidget(note)

    def _refresh_settlements(self):
        w=self.workspace;s=w.state;active=active_records(w);banks=[r for r in active.values() if r.role=="bank" and r.amount_minor]
        _options(self.refund_original,[(self.label(r.id),r.id) for r in banks]);self._refund_targets()
        _options(self.advance_cash,[(self.label(r.id),r.id) for r in banks if r.party])
        _options(self.advance_item,[(self.label(r.id),r.id) for r in active.values() if r.role in ("receivable","payable")])
        data=advance_rows(w);self.advance_ids=[p["id"] for p in data]
        _options(self.advance_combo,[(f'{p["id"]} / {p["kind"]} / {p["party"]} / 可用 {format_amount(p["remaining_minor"])}',p["id"]) for p in data])
        _populate(self.advance_table,("登记编号","类型","往来单位","原收付款","登记金额（元）","未核销余额（元）","依据","期间"),
                  [[p["id"],p["kind"],p["party"],self.label(p["cash"]),format_amount(p["amount_minor"]),format_amount(p["remaining_minor"]),p["evidence"],p["period"]] for p in data])
        self.refund_ids=list(s.refunds)
        _populate(self.refund_table,("编号","类别","原收付款","反向流水","金额（元）","原核销","预收预付","依据","期间"),
                  [[k,p["category"],self.label(p["original"]),self.label(p["cash"]),format_amount(p["amount_minor"]),p["allocation"],p["advance"],p["evidence"],p["period"]] for k,p in s.refunds.items()])

    def _refund_targets(self):
        rid=self.refund_original.currentData();s=self.workspace.state;record=self.workspace.records.get(rid)
        active=active_records(self.workspace)
        _options(self.refund_cash,[(self.label(r.id),r.id) for r in active.values() if record and r.role=="bank" and r.amount_minor*record.amount_minor<0 and r.day>=record.day])
        entries=[("原款项尚未分配部分",None)]
        entries += [(f'{k} / 原核销净额 {format_amount(allocation_net(s,k))} / {self.label(p["item"])}',"allocation:"+k) for k,p in s.allocations.items() if p["cash"]==rid]
        entries += [(f'{p["id"]} / {p["kind"]} / 未核销 {format_amount(p["remaining_minor"])}',"advance:"+p["id"]) for p in advance_rows(self.workspace) if p["cash"]==rid]
        _options(self.refund_target,entries)

    def refund_selected(self):
        target=self.refund_target.currentData();extra=dict([target.split(":",1)]) if target else {}
        self.apply("refund",original=self.refund_original.currentData(),cash=self.refund_cash.currentData(),amount_minor=parse_amount(self.refund_amount.text()),category=self.refund_category.currentText(),evidence=self.refund_evidence.text(),**extra)

    def register_advance_selected(self):
        self.apply("register_advance",cash=self.advance_cash.currentData(),amount_minor=parse_amount(self.advance_amount.text()),evidence=self.advance_evidence.text())

    def allocate_advance_selected(self):
        self.apply("allocate_advance",advance=self.advance_combo.currentData(),item=self.advance_item.currentData(),amount_minor=parse_amount(self.advance_allocation_amount.text()),note=self.advance_note.text())

    def refund_detail(self):
        p=self.workspace.state.refunds[self._choose(self.refund_table,self.refund_ids)]
        self.show_records((p["original"],p["cash"]),p["category"]+"依据："+p["evidence"])

    def advance_detail(self):
        p=self.workspace.state.advances[self._choose(self.advance_table,self.advance_ids)]
        self.show_records((p["cash"],),p["kind"]+"依据："+p["evidence"])
