from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
 QComboBox,QLineEdit,QTableView,QTabWidget,QSplitter,QPlainTextEdit,QHeaderView,QAbstractItemView)
from .table_models import DataTableModel
from ..review import classify_rows
from ..domain import Candidate
from ..amounts import format_amount

_RULES={"manual":"人工指定（已填写依据）","reference":"共同编号 + 金额","party_date":"日期 + 对方 + 金额","date_only":"同日同额 · 弱依据"}
_STATUS={"confirmed":"已确认","pending":"待复核","unmatched":"未匹配"}

def configure_table(table):
    table.setAlternatingRowColors(True);table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection);table.setWordWrap(False)
    table.verticalHeader().setDefaultSectionSize(43)
    table.horizontalHeader().setStretchLastSection(True);table.setShowGrid(False)

class ResultsPage(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.snapshot=None;self.candidate_ids=[];self.action_candidates={}
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(14)
        cards=QHBoxLayout();cards.setSpacing(14);self.stats=[]
        for label in ("银行记录","已确认关系","银行待复核","银行未匹配"):
            card=QFrame();card.setObjectName("card");box=QVBoxLayout(card);box.setContentsMargins(19,14,19,14)
            caption=QLabel(label);caption.setObjectName("statLabel");value=QLabel("—");value.setObjectName("statValue")
            box.addWidget(caption);box.addWidget(value);cards.addWidget(card);self.stats.append(value)
        layout.addLayout(cards)
        toolbar=QHBoxLayout();self.filter=QComboBox();self.filter.addItems(["全部状态","待复核","已确认","已拒绝","歧义","存在冲突"])
        self.search=QLineEdit();self.search.setPlaceholderText("搜索交易对方、日期、金额或共同编号")
        toolbar.addWidget(self.filter);toolbar.addWidget(self.search,1)
        self.confirm_button=QPushButton("确认所选");self.confirm_button.setObjectName("primary")
        self.reject_button=QPushButton("拒绝所选");self.undo_button=QPushButton("撤销所选")
        for b in (self.confirm_button,self.reject_button,self.undo_button):toolbar.addWidget(b)
        layout.addLayout(toolbar)
        split=QSplitter();self.tabs=QTabWidget()
        self.table=QTableView();configure_table(self.table);self.tabs.addTab(self.table,"匹配建议")
        self.records=QTableView();configure_table(self.records);self.tabs.addTab(self.records,"全部记录")
        self.exceptions=QTableView();configure_table(self.exceptions);self.tabs.addTab(self.exceptions,"差异与歧义")
        self.history=QTableView();configure_table(self.history);self.tabs.addTab(self.history,"操作记录")
        split.addWidget(self.tabs)
        detail=QFrame();detail.setObjectName("card");dbox=QVBoxLayout(detail);dbox.setContentsMargins(18,18,18,18)
        label=QLabel("原始记录与核对依据");label.setObjectName("cardTitle");dbox.addWidget(label)
        hint=QLabel("选择一条候选，查看双方原文和标准化金额。");hint.setWordWrap(True);hint.setObjectName("muted");dbox.addWidget(hint)
        self.detail=QPlainTextEdit();self.detail.setReadOnly(True);dbox.addWidget(self.detail,1)
        split.addWidget(detail);split.setSizes([860,330]);layout.addWidget(split,1)
        footer=QHBoxLayout();self.note=QLabel("候选不等于确认；导出会保留来源与人工状态。");self.note.setObjectName("muted")
        footer.addWidget(self.note,1);self.manual_button=QPushButton("手工指定一对一");footer.addWidget(self.manual_button);layout.addLayout(footer)
        self.filter.currentTextChanged.connect(self.refresh_candidates);self.search.textChanged.connect(self.refresh_candidates)
        self.tabs.currentChanged.connect(self.update_actions)
    def render(self,snapshot):
        self.snapshot=snapshot;states=classify_rows(snapshot)
        numbers=(len(snapshot.bank.transactions),len(snapshot.review.pairs),sum(states[t.id]=="pending" for t in snapshot.bank.transactions),sum(states[t.id]=="unmatched" for t in snapshot.bank.transactions))
        for widget,value in zip(self.stats,numbers):widget.setText(f"{value:,}")
        records=[]
        for ds in (snapshot.bank,snapshot.ledger):
            sources={r.id:r for r in ds.raw.rows}
            for t in ds.transactions:
                records.append(["银行" if t.role=="bank" else "日记账",t.day,format_amount(t.amount_minor),t.party,t.reference,_STATUS[states[t.id]],sources[t.id].source_line,t.summary,t.id])
        self.records.setModel(DataTableModel(("来源","日期","金额（元）","交易对方","共同编号","状态","源行","摘要","记录编号"),records,self.records))
        issues=[]
        bt={t.id:t for t in snapshot.bank.transactions};lt={t.id:t for t in snapshot.ledger.transactions}
        for d in snapshot.result.differences:issues.append(["金额差异",bt[d.bank_id].day,format_amount(d.delta_minor),d.reason,d.bank_id,d.ledger_id])
        for g in snapshot.result.groups:issues.append(["范围受限" if g.truncated else "歧义","",f"{len(g.bank_ids)} / {len(g.ledger_ids)} 笔",g.reason,", ".join(g.bank_ids),", ".join(g.ledger_ids)])
        for i in snapshot.result.issues:issues.append(["预检 "+i.severity,"","",i.message,"",""])
        self.exceptions.setModel(DataTableModel(("类型","日期","差额或组内笔数","说明","银行记录","日记账记录"),issues,self.exceptions))
        self.history.setModel(DataTableModel(("序号","操作","银行记录","日记账记录","备注"),[[e.sequence,e.kind,e.bank_id,e.ledger_id,e.note] for e in snapshot.review.events],self.history))
        self.note.setText(f"仅人工确认计入已确认结果  ·  {len(snapshot.result.groups)} 个歧义分组  ·  {len(snapshot.result.differences)} 个金额差异线索")
        self.refresh_candidates()
        for table in (self.records,self.exceptions,self.history):table.resizeColumnsToContents()
        self.update_actions()
    def update_actions(self,*args):
        active=self.tabs.currentIndex()==0 and self.snapshot is not None
        for button in (self.confirm_button,self.reject_button,self.undo_button):button.setEnabled(active)
    def refresh_candidates(self,*args):
        if self.snapshot is None:return
        s=self.snapshot;bt={t.id:t for t in s.bank.transactions};lt={t.id:t for t in s.ledger.transactions}
        br={r.id:r for r in s.bank.raw.rows};lr={r.id:r for r in s.ledger.raw.rows}
        states=classify_rows(s);confirmed={(p.bank_id,p.ledger_id) for p in s.review.pairs};rejected=set(s.review.rejected)
        group_rows={rid for g in s.result.groups for rid in g.bank_ids+g.ledger_ids}
        rows=[];ids=[];query=self.search.text().strip().casefold();filter_text=self.filter.currentText()
        self.action_candidates={c.id:c for c in s.result.candidates}
        suggested={(c.bank_id,c.ledger_id) for c in s.result.candidates}
        for p in s.review.pairs:
            if (p.bank_id,p.ledger_id) not in suggested:
                c=Candidate("manual:"+p.id,p.bank_id,p.ledger_id,"manual")
                self.action_candidates[c.id]=c
        for c in self.action_candidates.values():
            b,l=bt[c.bank_id],lt[c.ledger_id]
            if (c.bank_id,c.ledger_id) in confirmed:status="已确认"
            elif (c.bank_id,c.ledger_id) in rejected:status="已拒绝"
            elif states[b.id]=="confirmed" or states[l.id]=="confirmed":status="记录已占用"
            elif c.conflicts:status="存在冲突"
            elif b.id in group_rows or l.id in group_rows:status="歧义"
            else:status="待复核"
            row=[status,b.day,l.day,format_amount(b.amount_minor),b.party or l.party,b.reference or l.reference,_RULES[c.rule],br[b.id].source_line,lr[l.id].source_line]
            if filter_text!="全部状态" and status!=filter_text:continue
            if query and query not in " ".join(map(str,row)).casefold():continue
            rows.append(row);ids.append(c.id)
        self.candidate_ids=ids;self.table.setModel(DataTableModel(("状态","银行日期","账面日期","金额（元）","交易对方","共同编号","匹配依据","银行源行","账面源行"),rows,self.table))
        self.table.selectionModel().selectionChanged.connect(self.show_detail)
        self.table.resizeColumnsToContents()
        self.detail.setPlainText("选择候选查看证据。所有来源记录均保留，无法确定的关系交给人工复核。")
    def selected_candidates(self):
        return tuple(self.candidate_ids[i.row()] for i in self.table.selectionModel().selectedRows()) if self.table.selectionModel() else ()
    def show_detail(self,*args):
        ids=self.selected_candidates()
        if not ids:return
        c=self.action_candidates[ids[0]]
        sections=[f"匹配依据：{_RULES[c.rule]}",f"冲突提示：{', '.join(c.conflicts) or '无已识别字段冲突'}","候选关系仍需人工核实。"]
        if c.rule=="manual":
            pair=next(p for p in self.snapshot.review.pairs if (p.bank_id,p.ledger_id)==(c.bank_id,c.ledger_id))
            sections.append("人工确认依据："+pair.basis)
        for title,ds,rid in (("银行流水",self.snapshot.bank,c.bank_id),("银行日记账",self.snapshot.ledger,c.ledger_id)):
            r=next(r for r in ds.raw.rows if r.id==rid);t=next(t for t in ds.transactions if t.id==rid)
            sections += ["",f"── {title} ──",f"{ds.raw.filename} · {ds.raw.sheet or 'CSV'} · 第 {r.source_line} 行",f"标准化：{t.day}  {format_amount(t.amount_minor)} 元"]
            for n,cell in enumerate(r.cells):
                label=ds.raw.headers[n] if n<len(ds.raw.headers) else f"第 {n+1} 列"
                sections.append(f"{label}：{cell.value if cell.value is not None else '（空）'}")
                if cell.kind=="formula":sections.append(f"公式缓存值：{cell.cached_value}")
        self.detail.setPlainText("\n".join(sections))
