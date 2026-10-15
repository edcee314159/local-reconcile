from dataclasses import replace
from PySide6.QtCore import Qt,Signal
from PySide6.QtWidgets import (QWidget,QFrame,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,
    QPushButton,QComboBox,QSpinBox,QTableView,QLineEdit,QCheckBox,QHeaderView)
from .table_models import DataTableModel
from ..domain import MappingSpec,LocalReconcileError
from ..amounts import parse_amount,format_amount

_FIELDS=(("date_col","日期"),("amount_col","金额"),("income_col","收入列"),("expense_col","支出列"),
         ("party_col","交易对方"),("reference_col","共同编号"),("summary_col","摘要"),("account_col","账户列"),("currency_col","币种列"))
_GUESSES={"date_col":("日期","交易日期","记账日期"),"amount_col":("金额","交易金额","发生额"),"income_col":("收入","收入金额","收款金额"),
"expense_col":("支出","支出金额","付款金额"),"party_col":("对方","对方户名","交易对方"),"reference_col":("共同编号","业务编号"),
"summary_col":("摘要","用途"),"account_col":("本方账号","账户"),"currency_col":("币种",)}

class SourcePanel(QFrame):
    choose=Signal(str)
    reload=Signal(str)
    changed=Signal()
    def __init__(self,role,parent=None):
        super().__init__(parent);self.role=role;self.table=None;self.path=None;self.setObjectName("card")
        layout=QVBoxLayout(self);layout.setContentsMargins(18,16,18,16);layout.setSpacing(9)
        top=QHBoxLayout();title=QLabel("01  银行流水" if role=="bank" else "02  银行日记账");title.setObjectName("cardTitle")
        pick=QPushButton("选择文件");pick.setObjectName("small");pick.clicked.connect(lambda:self.choose.emit(role))
        top.addWidget(title);top.addStretch();top.addWidget(pick);layout.addLayout(top)
        self.file_label=QLabel("尚未选择文件 · .xlsx / .csv");self.file_label.setObjectName("muted");self.file_label.setWordWrap(True);layout.addWidget(self.file_label)
        row=QHBoxLayout();row.addWidget(QLabel("工作表"));self.sheet_combo=QComboBox();row.addWidget(self.sheet_combo,1)
        row.addWidget(QLabel("表头行"));self.header_spin=QSpinBox();self.header_spin.setRange(1,1000);row.addWidget(self.header_spin)
        reload_button=QPushButton("读取");reload_button.setObjectName("small");reload_button.clicked.connect(lambda:self.reload.emit(role));row.addWidget(reload_button);layout.addLayout(row)
        self.preview=QTableView();self.preview.setMinimumHeight(100);self.preview.setMaximumHeight(125);self.preview.setAlternatingRowColors(True)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents);layout.addWidget(self.preview)
        grid=QGridLayout();grid.setHorizontalSpacing(9);self.columns={}
        for n,(name,label) in enumerate(_FIELDS):
            combo=QComboBox();combo.setMinimumWidth(95);combo.addItem("未选择",None);self.columns[name]=combo
            grid.addWidget(QLabel(label),n//2,(n%2)*2);grid.addWidget(combo,n//2,(n%2)*2+1)
            combo.currentIndexChanged.connect(self._changed)
        layout.addLayout(grid)
        row=QHBoxLayout();row.addWidget(QLabel("金额方向"))
        self.direction=QComboBox();self.direction.addItem("正数收入 / 负数支出","signed");self.direction.addItem("正数支出 / 负数收入","inverted");self.direction.addItem("收入、支出分列","income_expense")
        self.direction.currentIndexChanged.connect(self._changed);row.addWidget(self.direction,1);layout.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel("日期格式"));self.date_format=QComboBox()
        for label,value in (("年月日自动识别",None),("日/月/年","%d/%m/%Y"),("月/日/年","%m/%d/%Y"),("年月日数字","%Y%m%d")):self.date_format.addItem(label,value)
        self.date_format.currentIndexChanged.connect(self._changed);row.addWidget(self.date_format,1);layout.addLayout(row)
        self.direction_preview=QLabel("确认后将统一为：收入正、支出负");self.direction_preview.setObjectName("muted");self.direction_preview.setWordWrap(True);layout.addWidget(self.direction_preview)
    def _changed(self,*args):
        self.update_direction_preview();self.changed.emit()
    def set_table(self,table,path,sheets=()):
        self.table=table;self.path=path;self.file_label.setText(table.filename+f"  ·  {len(table.rows):,} 行原始记录")
        self.sheet_combo.blockSignals(True);self.sheet_combo.clear();self.sheet_combo.addItems(list(sheets) or ["CSV"]);self.sheet_combo.setCurrentText(table.sheet or "CSV");self.sheet_combo.blockSignals(False)
        self.header_spin.setValue(table.header_row)
        self.preview.setModel(DataTableModel(table.headers,[[c.value for c in r.cells] for r in table.rows[:5]],self.preview))
        for name,combo in self.columns.items():
            combo.blockSignals(True);combo.clear();combo.addItem("未选择",None)
            for i,label in enumerate(table.headers):combo.addItem(f"{i+1}. {label}",i)
            guess=next((i for i,h in enumerate(table.headers) if h.strip() in _GUESSES[name]),None)
            combo.setCurrentIndex(guess+1 if guess is not None else 0);combo.blockSignals(False)
        if self.columns["amount_col"].currentData() is None and self.columns["income_col"].currentData() is not None and self.columns["expense_col"].currentData() is not None:self.direction.setCurrentIndex(2)
        else:self.direction.setCurrentIndex(0)
        self._changed()
    def mapping(self,account,confirmed):
        cols={name:combo.currentData() for name,combo in self.columns.items()}
        if cols["date_col"] is None:raise LocalReconcileError("mapping","请选择日期列")
        dual=self.direction.currentData()=="income_expense"
        if dual:cols["amount_col"]=None
        else:cols["income_col"]=cols["expense_col"]=None
        return MappingSpec(**cols,date_format=self.date_format.currentData(),direction=self.direction.currentData(),declared_account=account.strip(),declared_currency="CNY",confirmed=confirmed)
    def update_direction_preview(self):
        if self.table is None:return
        try:
            dual=self.direction.currentData()=="income_expense";values=[]
            for row in self.table.rows[:3]:
                def get(key):
                    i=self.columns[key].currentData()
                    if i is None or i>=len(row.cells):raise ValueError()
                    c=row.cells[i];return c.cached_value if c.kind=="formula" else c.value
                if dual:
                    inc=get("income_col");exp=get("expense_col")
                    cents=(0 if inc in ("",None) else parse_amount(inc))-(0 if exp in ("",None) else parse_amount(exp))
                else:
                    cents=parse_amount(get("amount_col"))*(-1 if self.direction.currentData()=="inverted" else 1)
                values.append(("收入 " if cents>=0 else "支出 ")+format_amount(abs(cents)))
            self.direction_preview.setText("方向预览： "+"  /  ".join(values))
        except (ValueError,TypeError):self.direction_preview.setText("选择金额列后显示方向预览；输入异常会在预检中列出")

class ImportPage(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(14)
        note=QLabel("导入同一账户的两份明细。先核实字段和收付方向，再开始核对。");note.setObjectName("muted");layout.addWidget(note)
        panels=QHBoxLayout();panels.setSpacing(16);self.bank=SourcePanel("bank");self.ledger=SourcePanel("ledger");panels.addWidget(self.bank);panels.addWidget(self.ledger);layout.addLayout(panels,1)
        bottom=QFrame();bottom.setObjectName("card");box=QVBoxLayout(bottom);box.setContentsMargins(18,14,18,14)
        row=QHBoxLayout();row.addWidget(QLabel("本次账户"));self.account=QLineEdit();self.account.setPlaceholderText("输入双方共同的银行账户标识");row.addWidget(self.account,1)
        row.addWidget(QLabel("人民币 CNY"));row.addSpacing(18);row.addWidget(QLabel("编号匹配日期容差"));self.tolerance=QSpinBox();self.tolerance.setRange(0,31);self.tolerance.setSuffix(" 天");row.addWidget(self.tolerance);box.addLayout(row)
        row=QHBoxLayout();self.confirm_box=QCheckBox("我已核实双方账户、人民币、字段与收付方向");row.addWidget(self.confirm_box);row.addStretch()
        self.run_button=QPushButton("开始核对  →");self.run_button.setObjectName("primary");row.addWidget(self.run_button);box.addLayout(row);layout.addWidget(bottom)
        self.bank.changed.connect(self.invalidate);self.ledger.changed.connect(self.invalidate);self.account.textChanged.connect(self.invalidate);self.tolerance.valueChanged.connect(self.invalidate)
    def invalidate(self,*args):self.confirm_box.setChecked(False)
