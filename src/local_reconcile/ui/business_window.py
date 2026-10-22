"""Interactive local workbench for the five business workflows."""
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QPushButton,
 QTabWidget,QTableView,QComboBox,QLineEdit,QDialog,QDialogButtonBox,QCheckBox,QSpinBox,QFileDialog,
 QMessageBox,QInputDialog,QPlainTextEdit,QSplitter,QAbstractItemView,QScrollArea)
from .workers import JobRunner
from .settlement_pages import SettlementPages
from .reporting_pages import ReportingPages
from .commercial_pages import CommercialPages
from .advanced_pages import AdvancedPages
from ..business.source_fields import SOURCE_FIELDS
from ..business.settlements import allocation_net
from .table_models import DataTableModel
from .results_page import configure_table
from .import_page import SourcePanel
from ..domain import LocalReconcileError,check_cancel
from ..amounts import parse_amount,format_amount
from ..importers import inspect_file,read_table
from ..project_store import load_project
from ..business.workspace import (new_workspace,add_account,add_batch,record_event,active_records,
                                relation_basis,period_end,_used,CATEGORIES,fail)
from ..business.matching import suggest_matches
from ..business.operations import outstanding,open_items,suggest_allocations,suggest_transfers,cash_remaining
from ..business.storage import save_workspace,load_workspace,export_workspace,import_legacy
from ..business.demo import make_demo

_NAMES={"bank":"银行流水","ledger":"银行日记账","receivable":"应收明细","payable":"应付明细","receivable_credit":"应收红字/退货折让","payable_credit":"应付红字/退货折让","partner_receivable":"客户对账单（我方应收口径）","partner_payable":"供应商对账单（我方应付口径）","settlement_order":"结算原订单","settlement_line":"结算组成明细","cutoff_business":"待核算业务（收货/验收/服务）","cutoff_entry":"实际记账明细（凭证行）"}

def button(text,callback):
    b=QPushButton(text);b.clicked.connect(lambda checked=False:callback());return b

def horizontal(layout,*widgets):
    row=QHBoxLayout()
    for widget in widgets:row.addWidget(widget)
    layout.addLayout(row);return row

def table(layout):
    t=QTableView();configure_table(t);t.setSelectionMode(QAbstractItemView.SingleSelection);layout.addWidget(t,1);return t

def populate(t,headers,rows):
    t.setModel(DataTableModel(headers,rows,t))
    t.resizeColumnsToContents()

class BusinessWindow(SettlementPages,ReportingPages,CommercialPages,AdvancedPages,QMainWindow):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle("业务核算 · 本地对账工作台");self.resize(1460,960);self.setMinimumSize(1100,780)
        self.workspace=new_workspace();self.analysis=None;self.dirty=False;self.path=None;self.busy=False;self.job_id=0;self.source_signature=None
        self.runner=JobRunner(self);self.runner.progress.connect(lambda stage,n,total:self.status.setText(f"{stage}  {n:,} / {total:,}" if total else stage))
        root=QWidget();root.setObjectName("root");self.setCentralWidget(root);layout=QVBoxLayout(root);layout.setContentsMargins(24,20,24,16);layout.setSpacing(12)
        self.period_label=QLabel();self.period_label.setObjectName("cardTitle")
        self.tools=QWidget();tools=QHBoxLayout(self.tools);tools.setContentsMargins(0,0,0,0);tools.addWidget(self.period_label,1)
        self.toolbar=[]
        for text,fn in (("新建",self.new_clicked),("登记账户",self.account_clicked),("导入明细",self.import_clicked),("虚构示例",self.demo_clicked),("打开工作区",self.open_clicked),("保存",self.save_clicked),("导出报告",self.export_clicked)):
            b=button(text,lambda fn=fn:self.guard(fn));tools.addWidget(b);self.toolbar.append(b)
        layout.addWidget(self.tools)
        self.summary=QLabel();self.summary.setWordWrap(True);self.summary.setObjectName("muted");layout.addWidget(self.summary)
        self.tabs=QTabWidget();self.tabs.setUsesScrollButtons(True);layout.addWidget(self.tabs,1)
        self._matching_page();self._differences_page();self._period_page();self._allocation_page();self._transfer_page();self._refund_page();self._advance_page();self._balance_page();self._aging_page();self._credit_page();self._duplicate_page();self._partner_page();self._net_settlement_page();self._cutoff_page()
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);self.detail.setMaximumHeight(115);self.detail.setPlaceholderText("选择记录查看原始文件、字段及核实依据。");layout.addWidget(self.detail)
        bottom=QHBoxLayout();self.status=QLabel("本地人民币业务核算 · 结果需人工确认");bottom.addWidget(self.status,1)
        self.legacy_button=button("导入旧版项目",lambda:self.guard(self.legacy_clicked));bottom.addWidget(self.legacy_button)
        self.cancel_button=button("取消任务",self.cancel);self.cancel_button.hide();bottom.addWidget(self.cancel_button);layout.addLayout(bottom)
        self.refresh()

    def guard(self,fn):
        try:return fn()
        except Exception as exc:
            message=str(exc) if isinstance(exc,LocalReconcileError) else "操作未完成，请检查输入、文件占用和保存目录。"
            self.status.setText(message);QMessageBox.warning(self,"请检查",message)

    def _page(self,name):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(14,14,14,14);layout.setSpacing(10);self.tabs.addTab(page,name);return layout

    def _matching_page(self):
        box=self._page("组合对账")
        self.analyze_button=button("分析候选",lambda:self.guard(self.analyze));self.confirm_button=button("确认所选",lambda:self.guard(self.confirm_selected));self.confirm_button.setObjectName("primary")
        self.window_days=QSpinBox();self.window_days.setRange(0,31);self.window_days.setSuffix(" 天");self.window_days.setValue(7);self.window_days.valueChanged.connect(self.settings_changed)
        horizontal(box,self.analyze_button,QLabel("组内日期跨度"),self.window_days,self.confirm_button,
                   button("拒绝候选",lambda:self.guard(self.reject_selected)),button("恢复拒绝",lambda:self.guard(self.restore_rejected)),
                   button("手工组合",lambda:self.guard(self.manual_match)))
        self.match_table=table(box)
        self.match_table.clicked.connect(lambda *_:self.match_detail())
        self.match_hint=QLabel("先登记账户并导入银行、日记账；支持一对多、多对多；自动每侧最多5笔，手工每侧最多100笔。");self.match_hint.setWordWrap(True);box.addWidget(self.match_hint)
        horizontal(box,QLabel("已确认对账关系"),button("撤销已确认",lambda:self.guard(self.undo_match)))
        self.confirmed_table=table(box);self.confirmed_table.clicked.connect(lambda *_:self.confirmed_detail())

    def _combo(self):
        c=QComboBox();c.setMinimumWidth(200);return c

    def _differences_page(self):
        box=self._page("差额分析");self.diff_bank=self._combo();self.diff_ledger=self._combo();self.diff_category=self._combo();self.diff_category.addItems(CATEGORIES)
        self.diff_evidence=QLineEdit();self.diff_evidence.setPlaceholderText("填写结算单、回单或其他核实依据；不能仅因差额小就认定为手续费")
        form=QFormLayout();form.addRow("银行记录",self.diff_bank);form.addRow("账面记录",self.diff_ledger);form.addRow("差额类别",self.diff_category);form.addRow("结算依据",self.diff_evidence);box.addLayout(form)
        horizontal(box,button("记录差额说明",lambda:self.guard(self.explain_selected)),button("撤销说明",lambda:self.guard(lambda:self.undo_table(self.difference_table,self.difference_ids,"undo_explain"))))
        hint=QLabel("差额已说明仍保留为未核对相符；原始金额保持不变。");hint.setObjectName("muted");box.addWidget(hint);self.difference_table=table(box)

    def _period_page(self):
        box=self._page("跨月未达")
        self.next_period=QLineEdit();self.next_period.setPlaceholderText("下一期间，例如 2026-11")
        self.period_view=self._combo();self.period_view.currentIndexChanged.connect(lambda *_:self.render_outstanding())
        horizontal(box,button("生成本期月末快照",lambda:self.guard(self.close_period)),self.next_period,button("进入下一期间",lambda:self.guard(lambda:self.apply("advance_period",period=self.next_period.text().strip()))),self.period_view)
        note=QLabel("月末快照记录当期未达与往来余额；后续核清不改变旧期间快照。已结账期间的补录需另建修订工作区。");note.setWordWrap(True);box.addWidget(note)
        self.outstanding_table=table(box);self.outstanding_table.clicked.connect(lambda *_:self.outstanding_detail())
        horizontal(box,button("排除所选重复/非业务记录",lambda:self.guard(self.exclude_selected)),button("恢复已排除记录",lambda:self.guard(self.restore_excluded)))
        self.snapshot_table=table(box)

    def _allocation_page(self):
        box=self._page("应收应付核销");self.cash_combo=self._combo();self.item_combo=self._combo();self.allocation_amount=QLineEdit();self.allocation_amount.setPlaceholderText("本次分配金额（元）");self.allocation_note=QLineEdit();self.allocation_note.setPlaceholderText("核实依据；跨单位分配必须填写")
        form=QFormLayout();form.addRow("银行收付款",self.cash_combo);form.addRow("应收/应付单据",self.item_combo)
        form.addRow("本次核销金额（元）",self.allocation_amount);form.addRow("核实依据",self.allocation_note);box.addLayout(form)
        horizontal(box,button("确认本次核销",lambda:self.guard(self.allocate_selected)),button("生成同单位候选",lambda:self.guard(self.allocation_suggestions)),button("撤销所选核销",lambda:self.guard(lambda:self.undo_table(self.allocation_table,self.allocation_ids,"undo_allocate"))))
        self.allocation_candidate_table=table(box);self.allocation_candidate_table.setMaximumHeight(130);self.allocation_candidate_table.clicked.connect(lambda *_:self.pick_allocation())
        self.open_item_table=table(box);self.open_item_table.clicked.connect(lambda *_:self.item_detail())
        self.allocation_table=table(box)

    def _transfer_page(self):
        box=self._page("多账户转账");self.outgoing_combo=self._combo();self.incoming_combo=self._combo();self.transfer_fee=QLineEdit("0");self.transfer_evidence=QLineEdit();self.transfer_evidence.setPlaceholderText("确认双方均为本企业账户及转账业务的依据；有手续费时注明回单")
        form=QFormLayout();form.addRow("转出账户记录",self.outgoing_combo);form.addRow("转入账户记录",self.incoming_combo);form.addRow("已核实手续费（元）",self.transfer_fee);form.addRow("核实依据",self.transfer_evidence);box.addLayout(form)
        horizontal(box,button("查找转账候选",lambda:self.guard(self.transfer_suggestions)),button("确认内部转账",lambda:self.guard(self.transfer_selected)),button("撤销转账关系",lambda:self.guard(lambda:self.undo_table(self.transfer_table,self.transfer_ids,"undo_transfer"))))
        self.transfer_candidate_table=table(box);self.transfer_candidate_table.setMaximumHeight(150);self.transfer_candidate_table.clicked.connect(lambda *_:self.pick_transfer())
        self.transfer_table=table(box)
        note=QLabel("内部转账分类和银行—账面对账分别管理；内部转账记录不能再用于客户/供应商核销。");note.setWordWrap(True);box.addWidget(note)

    def label(self,rid):
        r=self.workspace.records[rid]
        return f"{r.account or _NAMES[r.role]}  {r.day}  {format_amount(r.amount_minor)}  {r.party}  {r.reference}"

    def _choose(self,table,values):
        indexes=table.selectionModel().selectedRows() if table.selectionModel() else ()
        if len(indexes)!=1:fail("请先选中一行")
        return values[indexes[0].row()]

    def _fill(self,combo,records):
        current=combo.currentData();combo.blockSignals(True);combo.clear()
        for r in records:combo.addItem(self.label(r.id),r.id)
        index=combo.findData(current)
        if index>=0:combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def set_workspace(self,w):
        self.workspace=w;self.analysis=None;self.source_signature=None;self.refresh()

    def refresh(self):
        w=self.workspace;s=w.state;active=active_records(w)
        self.period_label.setText(f"业务核算  /  {s.period}"+(" · 已结账" if s.period in s.closings else ""))
        self.summary.setText(f"{len(w.accounts)} 个本企业人民币账户  ·  {len(active):,} 条本期可见记录  ·  {len(s.matches)} 组已确认对账  ·  {len(s.allocations)} 条往来核销  ·  {len(s.transfers)} 组内部转账")
        editable=s.period not in s.closings
        self.window_days.blockSignals(True);self.window_days.setValue(w.settings.window_days);self.window_days.blockSignals(False)
        self.window_days.setEnabled(not any(e.kind!="import_batch" for e in w.events))
        signature=(tuple(b.id for b in w.batches),s.period,tuple(a.code for a in w.accounts))
        if signature!=self.source_signature:
            self.analysis=None;self.source_signature=signature
            banks=[r for r in active.values() if r.role=="bank"];ledgers=[r for r in active.values() if r.role=="ledger"];items=[r for r in active.values() if r.role in ("receivable","payable")]
            for combo,rows in ((self.diff_bank,banks),(self.diff_ledger,ledgers),(self.cash_combo,banks),(self.item_combo,items),(self.outgoing_combo,[r for r in banks if r.amount_minor<0]),(self.incoming_combo,[r for r in banks if r.amount_minor>0])):self._fill(combo,rows)
        self.render_matches()
        self.confirmed_ids=list(s.matches)
        populate(self.confirmed_table,("关系","银行笔数","账面笔数","合计（元）","确认依据","期间"),
                 [[rid,len(p["left"]),len(p["right"]),format_amount(p["amount_minor"]),p["note"] or p["basis"],p["period"]] for rid,p in s.matches.items()])
        self.difference_ids=list(s.explanations)
        populate(self.difference_table,("银行记录","账面记录","差额（元）","类别","结算依据","状态"),
                 [[self.label(p["bank"]),self.label(p["ledger"]),format_amount(p["delta_minor"]),p["category"],p["evidence"],"待查" if p["category"]=="待查" else "差额已说明，未视作相符"] for p in s.explanations.values()])
        selected=self.period_view.currentData();self.period_view.blockSignals(True);self.period_view.clear();self.period_view.addItem("当前未达",None)
        for period in sorted(s.closings):self.period_view.addItem(period+" 月末快照",period)
        ix=self.period_view.findData(selected);self.period_view.setCurrentIndex(max(0,ix));self.period_view.blockSignals(False);self.render_outstanding()
        self.open_item_rows=open_items(w)
        populate(self.open_item_table,("类型","往来单位","单据编号","原金额（元）","资金净核销（元）","红字抵减（元）","未结清（元）","账龄（天）","到期日","逾期（天）"),
          [[_NAMES[i["record"].role],i["record"].party,i["record"].reference,format_amount(i["record"].amount_minor),format_amount(i["allocated_minor"]),format_amount(i["credited_minor"]),format_amount(i["remaining_minor"]),i["age_days"],i["record"].due or "",i["overdue_days"] if i["overdue_days"] is not None else "未提供"] for i in self.open_item_rows])
        self.allocation_ids=list(s.allocations)
        populate(self.allocation_table,("银行收付款","往来单据","原核销金额（元）","退款后净核销（元）","预收预付登记","核实依据","期间"),
                 [[self.label(p["cash"]),self.label(p["item"]),format_amount(p["amount_minor"]),format_amount(allocation_net(s,k)),p.get("advance",""),p["note"],p["period"]] for k,p in s.allocations.items()])
        self.transfer_ids=list(s.transfers)
        populate(self.transfer_table,("转出记录","转入记录","转入金额（元）","手续费（元）","依据","期间"),
                 [[self.label(p["outgoing"]),self.label(p["incoming"]),format_amount(p["amount_minor"]),format_amount(p["fee_minor"]),p["evidence"],p["period"]] for p in s.transfers.values()])
        self._refresh_settlements()
        self._refresh_reporting()
        self._refresh_commercial()
        self._refresh_advanced()
        self.allocation_candidates=();self.transfer_candidates=()
        populate(self.allocation_candidate_table,("候选银行记录","候选单据","建议金额（元）"),[])
        populate(self.transfer_candidate_table,("候选转出","候选转入"),[])

    def render_matches(self):
        s=self.workspace.state;rows=[];used=_used(s.matches);confirmed={(p["left"],p["right"]) for p in s.matches.values()}
        for c in self.analysis.candidates if self.analysis else ():
            key=c.left,c.right
            status="已确认" if key in confirmed else "已拒绝" if key in s.rejected else "记录已占用" if used.intersection(c.left+c.right) else "存在冲突" if c.conflicts else "待复核"
            rows.append([status,len(c.left),len(c.right),format_amount(c.amount_minor),c.basis,"；".join(c.conflicts),self.label(c.left[0]),self.label(c.right[0])])
        populate(self.match_table,("状态","银行笔数","账面笔数","合计（元）","匹配依据","冲突","银行首笔","账面首笔"),rows)
        if self.analysis:
            self.match_hint.setText(f"{len(self.analysis.candidates)} 个候选；{len(self.analysis.ranges)} 个范围受限组。候选只表示建议，需逐组核实。\n"+"；".join(r.reason+f"（{len(r.rows)}笔）" for r in self.analysis.ranges[:3]))

    def render_outstanding(self):
        if not hasattr(self,"outstanding_table"):return
        s=self.workspace.state;period=self.period_view.currentData()
        rows=([self.workspace.records[rid] for rid in s.closings[period]["outstanding"]] if period else [i["record"] for i in outstanding(self.workspace)])
        self.outstanding_ids=[r.id for r in rows];end=period_end(period or s.period)
        populate(self.outstanding_table,("来源","账户","日期","金额（元）","往来单位","共同编号","账龄（天）"),
                 [[_NAMES[r.role],r.account,r.day,format_amount(r.amount_minor),r.party,r.reference,(end-r.day).days] for r in rows])
        balances=s.closings[period]["open_items"] if period else {}
        populate(self.snapshot_table,("当期往来单据","月末未结清（元）"),[[self.label(rid),format_amount(amount)] for rid,amount in balances.items()])

    def apply(self,event_kind,**data):
        self.workspace=record_event(self.workspace,event_kind,**data);self.dirty=True;self.refresh();self.status.setText("业务操作已记录 · 原始来源保留")

    def _run(self,work,done):
        if self.busy:fail("请等待当前任务完成")
        self.busy=True;self.job_id+=1;self.tools.setEnabled(False);self.tabs.setEnabled(False);self.legacy_button.setEnabled(False);self.cancel_button.show();self.status.setText("正在处理…")
        def finish(result):
            self.busy=False;self.tools.setEnabled(True);self.tabs.setEnabled(True);self.legacy_button.setEnabled(True);self.cancel_button.hide()
            self.guard(lambda:done(result))
        def error(exc):
            self.busy=False;self.tools.setEnabled(True);self.tabs.setEnabled(True);self.legacy_button.setEnabled(True);self.cancel_button.hide()
            self.guard(lambda:(_ for _ in ()).throw(exc))
        self.runner.submit(self.job_id,work,finish,error)

    def cancel(self):
        self.runner.cancel(self.job_id);self.busy=False;self.tools.setEnabled(True);self.tabs.setEnabled(True);self.legacy_button.setEnabled(True);self.cancel_button.hide();self.status.setText("已请求取消；后台退出后执行后续任务，当前工作区保留")

    def analyze(self):
        w=self.workspace
        def done(result):self.analysis=result;self.render_matches();self.status.setText("候选分析完成，确认前请查看双方原始记录")
        self._run(lambda progress,cancelled:suggest_matches(w,progress,cancelled),done)

    def candidate(self):
        if not self.analysis:fail("请先分析候选")
        return self._choose(self.match_table,self.analysis.candidates)

    def confirm_selected(self):
        c=self.candidate();note=""
        if c.conflicts or c.basis.startswith("同日同额"):
            note,ok=QInputDialog.getText(self,"核实依据","请核实关系并填写依据：")
            if not ok:return
        self.apply("confirm_match",left=c.left,right=c.right,note=note)

    def reject_selected(self):
        c=self.candidate();self.apply("reject_match",left=c.left,right=c.right,note="人工拒绝候选")

    def restore_rejected(self):
        c=self.candidate();self.apply("undo_reject",left=c.left,right=c.right,note="重新复核")

    def undo_match(self):self.undo_table(self.confirmed_table,self.confirmed_ids,"undo_match")
    def undo_table(self,t,values,kind):self.apply(kind,target=self._choose(t,values),note="人工撤销")

    def show_records(self,ids,extra=""):
        lines=[extra] if extra else []
        for rid in ids:
            r=self.workspace.records[rid];b=next(b for b in self.workspace.batches if b.id==r.batch_id);raw=next(row for row in b.raw.rows if row.id==r.source_id)
            lines += ["",self.label(rid),f"来源：{b.raw.filename} / {b.raw.sheet or 'CSV'} / 第{raw.source_line}行"]
            lines += [f"{b.raw.headers[i] if i<len(b.raw.headers) else i+1}：{cell.value}" for i,cell in enumerate(raw.cells)]
        self.detail.setPlainText("\n".join(lines))

    def match_detail(self):
        if not self.analysis:return
        c=self.candidate();self.show_records(c.left+c.right,"匹配依据："+c.basis+"；冲突："+"、".join(c.conflicts))

    def confirmed_detail(self):
        key=self._choose(self.confirmed_table,self.confirmed_ids);p=self.workspace.state.matches[key];self.show_records(p["left"]+p["right"],"确认依据："+(p["note"] or p["basis"]))

    def outstanding_detail(self):
        if self.outstanding_ids:self.show_records((self._choose(self.outstanding_table,self.outstanding_ids),))
    def item_detail(self):
        if self.open_item_rows:self.show_records((self._choose(self.open_item_table,self.open_item_rows)["record"].id,))

    def manual_match(self):
        d=QDialog(self);d.setWindowTitle("手工指定组合 · 每侧最多100笔，合计相等且方向一致");d.resize(1100,700);box=QVBoxLayout(d)
        banks=[r for r in active_records(self.workspace).values() if r.role=="bank"];ledgers=[r for r in active_records(self.workspace).values() if r.role=="ledger"]
        left=table(box);right=table(box)
        for t,rows in ((left,banks),(right,ledgers)):
            t.setSelectionMode(QAbstractItemView.ExtendedSelection);populate(t,("记录",),[[self.label(r.id)] for r in rows])
        note=QLineEdit();note.setPlaceholderText("填写查明组合关系的业务依据");box.addWidget(note);buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);box.addWidget(buttons)
        if d.exec()==QDialog.Accepted:
            if not note.text().strip():fail("手工指定请填写依据")
            self.apply("confirm_match",left=[banks[i.row()].id for i in left.selectionModel().selectedRows()],right=[ledgers[i.row()].id for i in right.selectionModel().selectedRows()],note=note.text())

    def explain_selected(self):
        self.apply("explain",bank=self.diff_bank.currentData(),ledger=self.diff_ledger.currentData(),category=self.diff_category.currentText(),evidence=self.diff_evidence.text())

    def close_period(self):
        if QMessageBox.question(self,"生成月末快照","生成快照后本期间停止修改，需进入下一期间继续处理。是否生成？",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes:self.apply("close_period")

    def allocation_suggestions(self):
        w=self.workspace
        def done(result):
            self.allocation_candidates=result;populate(self.allocation_candidate_table,("候选银行记录","候选单据","建议金额（元）"),[[self.label(b),self.label(i),format_amount(a)] for b,i,a in result]);self.status.setText("按同一往来单位生成候选，最多展开每个单位100张单据；未穷尽时可手工选择，仍需核实。")
        self._run(lambda progress,cancelled:suggest_allocations(w,cancelled),done)

    def pick_allocation(self):
        b,i,amount=self._choose(self.allocation_candidate_table,self.allocation_candidates)
        self.cash_combo.setCurrentIndex(self.cash_combo.findData(b));self.item_combo.setCurrentIndex(self.item_combo.findData(i));self.allocation_amount.setText(format_amount(amount));self.show_records((b,i))

    def allocate_selected(self):
        self.apply("allocate",cash=self.cash_combo.currentData(),item=self.item_combo.currentData(),amount_minor=parse_amount(self.allocation_amount.text()),note=self.allocation_note.text())

    def transfer_suggestions(self):
        w=self.workspace
        def done(result):
            self.transfer_candidates=result;populate(self.transfer_candidate_table,("候选转出","候选转入"),[[self.label(o),self.label(i)] for o,i in result]);self.status.setText("候选基于日期、等额及编号/名称，仅为建议；逐笔核实两个账户及业务依据。")
        self._run(lambda progress,cancelled:suggest_transfers(w,cancelled),done)

    def pick_transfer(self):
        o,i=self._choose(self.transfer_candidate_table,self.transfer_candidates)
        self.outgoing_combo.setCurrentIndex(self.outgoing_combo.findData(o));self.incoming_combo.setCurrentIndex(self.incoming_combo.findData(i));self.show_records((o,i))

    def transfer_selected(self):
        self.apply("confirm_transfer",outgoing=self.outgoing_combo.currentData(),incoming=self.incoming_combo.currentData(),fee_minor=parse_amount(self.transfer_fee.text()),evidence=self.transfer_evidence.text())

    def exclude_selected(self):
        if self.period_view.currentData():fail("历史快照只读，请切换当前未达")
        rid=self._choose(self.outstanding_table,self.outstanding_ids);note,ok=QInputDialog.getText(self,"排除来源记录","请填写重复或非业务依据；原始记录仍保留：")
        if ok:self.apply("exclude",row=rid,note=note)

    def restore_excluded(self):
        ids=sorted(self.workspace.state.excluded)
        if not ids:fail("没有已排除记录")
        labels=[self.label(rid) for rid in ids];choice,ok=QInputDialog.getItem(self,"恢复来源","选择恢复记录",labels,0,False)
        if ok:self.apply("undo_exclude",row=ids[labels.index(choice)],note="人工恢复")

    def settings_changed(self,value):
        if self.busy:return
        def change():
            if any(e.kind!="import_batch" for e in self.workspace.events):fail("已产生业务操作，请在新工作区调整规则")
            self.workspace=replace(self.workspace,settings=replace(self.workspace.settings,window_days=value));self.analysis=None;self.dirty=True;self.refresh()
        self.guard(change)

    def discard_ok(self):
        return not self.dirty or QMessageBox.question(self,"尚未保存","当前业务工作区未保存，是否放弃并继续？",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes

    def new_clicked(self):
        if not self.discard_ok():return
        period,ok=QInputDialog.getText(self,"新建业务工作区","起始期间（YYYY-MM）",text=self.workspace.state.period)
        if ok:self.set_workspace(new_workspace(period.strip()));self.path=None;self.dirty=False

    def account_clicked(self):
        d=QDialog(self);d.setWindowTitle("登记本企业人民币银行账户");form=QFormLayout(d);code=QLineEdit();name=QLineEdit();confirmed=QCheckBox("我已确认这是本企业的人民币银行账户")
        form.addRow("账户标识/账号",code);form.addRow("账户名称",name);form.addRow(confirmed)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);form.addRow(buttons)
        if d.exec()==QDialog.Accepted:
            if not confirmed.isChecked():fail("请确认账户归属与人民币币种")
            self.workspace=add_account(self.workspace,code.text(),name.text());self.dirty=True;self.refresh()

    def import_clicked(self):
        path,_=QFileDialog.getOpenFileName(self,"导入银行/账面/往来明细","","表格 (*.xlsx *.csv)")
        if not path:return
        self._run(lambda progress,cancelled:inspect_file(path,"bank"),lambda sheets:self.import_options(Path(path),sheets))

    def import_options(self,path,sheets):
        d=QDialog(self);d.setWindowTitle("选择来源与期间口径");form=QFormLayout(d);role=QComboBox()
        for key,name in _NAMES.items():role.addItem(name,key)
        account=QComboBox()
        for a in self.workspace.accounts:account.addItem(a.label+" / "+a.code,a.code)
        sheet=QComboBox();sheet.addItems(list(sheets) or ["CSV"]);header=QSpinBox();header.setRange(1,1000)
        form.addRow("来源类别",role);form.addRow("本企业人民币账户",account);form.addRow("工作表",sheet);form.addRow("表头行",header)
        role.currentIndexChanged.connect(lambda *_:account.setEnabled(role.currentData() in ("bank","ledger")))
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);form.addRow(buttons)
        if d.exec()!=QDialog.Accepted:return
        kind=role.currentData();code=account.currentData() if kind in ("bank","ledger") else ""
        if kind in ("bank","ledger") and not code:fail("请先登记本企业人民币账户")
        sheet_name=None if sheet.currentText()=="CSV" else sheet.currentText();line=header.value()
        self._run(lambda progress,cancelled:read_table(path,"bank" if kind=="bank" else "ledger",sheet_name,line,progress,cancelled),
                  lambda raw:self.mapping_dialog(raw,kind,code,path))

    def mapping_dialog(self,raw,role,account,path):
        d=QDialog(self);d.setWindowTitle("确认字段 · "+_NAMES[role]);d.resize(840,840);outer=QVBoxLayout(d);scroll=QScrollArea();scroll.setWidgetResizable(True);container=QWidget();box=QVBoxLayout(container);scroll.setWidget(container);outer.addWidget(scroll);panel=SourcePanel(raw.role);panel.set_table(raw,path)
        for b in panel.findChildren(QPushButton):b.hide()
        panel.sheet_combo.setEnabled(False);panel.header_spin.setEnabled(False)
        panel.layout().itemAt(0).layout().itemAt(0).widget().setText(_NAMES[role])
        if role not in ("bank","ledger"):
            for name,aliases in (("reference_col",("单据编号","发票号码","发票号","单据号")),("amount_col",("单据金额","应收金额","应付金额","未结余额","未结清余额","对账余额","红字金额","折让金额")),("party_col",("客户","供应商","往来单位","客户名称","供应商名称"))):
                index=next((i for i,h in enumerate(raw.headers) if h.strip() in aliases),None)
                if index is not None:panel.columns[name].setCurrentIndex(index+1)
        if role in ("settlement_order","settlement_line","cutoff_business","cutoff_entry"):
            reference_aliases=("结算行号","结算明细行号") if role=="settlement_line" else ("业务编号","业务单号") if role.startswith("cutoff_") else ("订单号","订单编号")
            for name,aliases in (("reference_col",reference_aliases),("amount_col",("确认金额","业务金额","订单金额","结算金额","金额")),("date_col",("业务日期","记账日期","结算日期","日期")),("party_col",("平台","单位","往来单位","交易对方"))):
                index=next((i for i,h in enumerate(raw.headers) if h.strip() in aliases),None)
                if index is not None:panel.columns[name].setCurrentIndex(index+1)
        box.addWidget(panel)
        extra_controls={};extra_form=QFormLayout()
        for key,(label,required,aliases) in SOURCE_FIELDS.get(role,{}).items():
            combo=QComboBox();combo.addItem("请选择（必填）" if required else "不提供",None)
            for i,h in enumerate(raw.headers):combo.addItem(h,i)
            guessed=next((i for i,h in enumerate(raw.headers) if h.strip() in aliases),None)
            if guessed is not None:combo.setCurrentIndex(guessed+1)
            extra_form.addRow(label,combo);extra_controls[key]=combo
        box.addLayout(extra_form)
        due=QComboBox();due.addItem("不提供到期日",None)
        for i,h in enumerate(raw.headers):due.addItem(h,i)
        if role in ("receivable","payable"):
            horizontal(box,QLabel("到期日（可选）"),due)
        hint="对方表须为每张单据一行的非负未结余额，按我方应收/应付口径填写，日期为原单据日期" if role.startswith("partner_") else "红字、退货、折让金额可正可负，作为抵减额度；每张单据一行" if role.endswith("_credit") else "应收应付为每张单据一行的正数金额"
        hints={"settlement_order":"每张原订单一行正数订单金额；编号为原订单号，单位使用平台/结算对方口径。",
               "settlement_line":"金额：销售和其他加款为正，退款/佣金/运费/其他扣款为负；共同编号字段映射结算行唯一号，另选结算批次和原订单字段。",
               "cutoff_business":"业务日期为收货/验收/业务发生日；金额为财务确认的待核算总额，业务编号须唯一，归属规则在业务页人工登记。",
               "cutoff_entry":"日期为记账日期，金额为对应业务的确认金额（冲销为负）；共同编号映射业务编号，另选凭证行唯一编号。与业务基础使用一致金额口径。"}
        hint=hints.get(role,hint)
        text=QLabel(hint);text.setWordWrap(True);box.addWidget(text)
        confirmed=QCheckBox("已核实字段、金额方向、人民币及来源口径");box.addWidget(confirmed)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);outer.addWidget(buttons)
        if d.exec()!=QDialog.Accepted:return
        mapping=panel.mapping(account or "OPEN-ITEMS",confirmed.isChecked());w=self.workspace;due_col=due.currentData() if role in ("receivable","payable") else None
        extra_cols={key:combo.currentData() for key,combo in extra_controls.items() if combo.currentData() is not None}
        def work(progress,cancelled):
            check_cancel(cancelled);result=add_batch(w,role,account,raw,mapping,due_col,extra_cols);check_cancel(cancelled);return result
        def done(result):self.set_workspace(result);self.dirty=True;self.status.setText("来源已导入；同一来源不会重复添加。请分析候选或进入相应业务页。")
        self._run(work,done)

    def demo_clicked(self):
        if not self.discard_ok():return
        choice,ok=QInputDialog.getItem(self,"载入虚构示例","选择示例：",["综合业务（含退款、预收预付、账龄）","月末余额调节与逾期分析","红字退货、重复检查与双方往来对账","净到账还原与月末核算检查"],0,False)
        if not ok:return
        from ..business.reporting_smoke import reporting_demo
        from ..business.commercial_demo import commercial_demo
        from ..business.advanced_demo import advanced_demo
        factory=advanced_demo if choice.startswith("净到账") else commercial_demo if choice.startswith("红字") else reporting_demo if choice.startswith("月末") else make_demo
        self._run(lambda progress,cancelled:factory(),lambda w:(self.set_workspace(w),setattr(self,"dirty",True),setattr(self,"path",None),self.status.setText("已载入虚构示例，可进入相应业务页复核。")))

    def save_to(self,path,close_after=False):
        w=self.workspace
        def done(_):
            self.path=Path(path);self.dirty=False;self.status.setText("业务工作区已保存；包含未加密的来源快照与操作记录")
            if close_after:self.close()
        self._run(lambda progress,cancelled:save_workspace(w,path,cancelled),done)

    def save_clicked(self,close_after=False):
        path=self.path
        if path is None:
            name,_=QFileDialog.getSaveFileName(self,"保存业务工作区（包含未加密明细）","业务核算.lrwork","业务工作区 (*.lrwork)")
            if not name:return
            path=Path(name)
        self.save_to(path,close_after)

    def load_from(self,path):
        def done(w):self.set_workspace(w);self.path=Path(path);self.dirty=False;self.status.setText("业务工作区已打开并重放验证")
        self._run(lambda progress,cancelled:load_workspace(path),done)

    def open_clicked(self):
        if not self.discard_ok():return
        path,_=QFileDialog.getOpenFileName(self,"打开业务工作区","","业务工作区 (*.lrwork)")
        if path:self.load_from(path)

    def legacy_clicked(self):
        if not self.discard_ok():return
        path,_=QFileDialog.getOpenFileName(self,"验证导入旧版项目；原文件保持不变","","旧版项目 (*.lrproj)")
        if not path:return
        def work(progress,cancelled):
            s=load_project(path);check_cancel(cancelled);latest=max(t.day for ds in (s.bank,s.ledger) for t in ds.transactions)
            return import_legacy(s,latest.strftime("%Y-%m"))
        def done(w):self.set_workspace(w);self.path=None;self.dirty=True;self.status.setText("旧项目已验证导入，请另存为新的业务工作区；原项目保持不变。")
        self._run(work,done)

    def export_to(self,path):
        w=self.workspace;self._run(lambda progress,cancelled:export_workspace(w,path,cancelled),lambda _:self.status.setText("核算报告已导出，包含对账、差额、未达、核销、转账、退款、预收预付与原始记录"))

    def export_clicked(self):
        path,_=QFileDialog.getSaveFileName(self,"导出业务核算报告","业务核算报告.xlsx","Excel (*.xlsx)")
        if path:self.export_to(path)

    def closeEvent(self,event):
        if self.dirty:
            answer=QMessageBox.question(self,"尚未保存","保存当前业务工作区后退出？",QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Cancel)
            if answer==QMessageBox.Save:
                self.guard(lambda:self.save_clicked(True));event.ignore();return
            if answer!=QMessageBox.Discard:event.ignore();return
        self.runner.shutdown();event.accept()
