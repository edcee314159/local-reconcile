"""Reviewed bank balance adjustment and customer/vendor aging views."""
from PySide6.QtWidgets import QFormLayout,QLabel,QLineEdit,QComboBox,QCheckBox
from .settlement_pages import _button,_row,_table,_populate,_options
from ..amounts import parse_amount,format_amount
from ..business.workspace import active_records,_used
from ..business.reporting import bank_statement,aging_report,summarize_aging,timing_category,AGE_BUCKETS

_NAMES={"bank":"银行流水","ledger":"日记账","receivable":"应收款","payable":"应付款"}


class ReportingPages:
    def _balance_page(self):
        box=self._page("余额调节表");self.balance_account=self._combo();self.balance_period=self._combo()
        _row(box,QLabel("账户"),self.balance_account,QLabel("报告期间"),self.balance_period)
        self.bank_closing=QLineEdit();self.ledger_closing=QLineEdit();self.balance_evidence=QLineEdit()
        self.bank_closing.setPlaceholderText("银行对账单期末余额，可为负数")
        self.ledger_closing.setPlaceholderText("银行存款日记账期末余额")
        form=QFormLayout();form.addRow("银行期末余额（元）",self.bank_closing);form.addRow("账面期末余额（元）",self.ledger_closing);form.addRow("余额资料依据",self.balance_evidence);box.addLayout(form)
        self.save_balance_button=_button(self,"保存本账户期末余额",self.save_balances_selected);box.addWidget(self.save_balance_button)
        self.balance_status=QLabel();self.balance_status.setWordWrap(True);box.addWidget(self.balance_status)
        self.balance_table=_table(box);self.balance_table.setMaximumHeight(205)
        self.adjustment_row=self._combo();self.adjustment_category=QComboBox();self.adjustment_evidence=QLineEdit()
        form=QFormLayout();form.addRow("未达来源记录",self.adjustment_row);form.addRow("核实后的未达类别",self.adjustment_category);form.addRow("回单 / 核实依据",self.adjustment_evidence);box.addLayout(form)
        self.classify_button=_button(self,"确认本笔未达类别",self.classify_selected)
        self.unclassify_button=_button(self,"撤销本笔未达分类",self.unclassify_selected)
        _row(box,self.classify_button,self.unclassify_button)
        note=QLabel("先核实未达性质，再参与余额调节。待查项目单独保留；余额未录入、存在待复核项目或仍有差额时均不显示相符。仅核对余额，不生成调账分录。")
        note.setWordWrap(True);box.addWidget(note);self.adjustment_table=_table(box)
        self.adjustment_table.clicked.connect(lambda *_:self.guard(self.adjustment_detail))
        self.balance_account.currentIndexChanged.connect(lambda *_:self.guard(self.render_bank_statement))
        self.balance_period.currentIndexChanged.connect(lambda *_:self.guard(self.render_bank_statement))
        self.adjustment_row.currentIndexChanged.connect(lambda *_:self._adjustment_category())

    def _aging_page(self):
        box=self._page("账龄与逾期");self.aging_period=self._combo();self.aging_role=QComboBox()
        self.aging_role.addItem("应收和应付",None);self.aging_role.addItem("应收款","receivable");self.aging_role.addItem("应付款","payable")
        self.aging_party=QLineEdit();self.aging_party.setPlaceholderText("筛选客户 / 供应商名称")
        self.aging_overdue=QCheckBox("仅显示已逾期")
        _row(box,QLabel("报告期间"),self.aging_period,self.aging_role,self.aging_party,self.aging_overdue)
        self.aging_status=QLabel();self.aging_status.setWordWrap(True);box.addWidget(self.aging_status)
        note=QLabel("账龄按单据日期计算，逾期按到期日计算；仅统计未结清余额，应收与应付分别列示。没有到期日不推定逾期。历史月末报告保留当时余额。导出报告含完整清单，可用于催收与付款核查。")
        note.setWordWrap(True);box.addWidget(note)
        self.aging_summary_table=_table(box);self.aging_detail_table=_table(box)
        self.aging_detail_table.clicked.connect(lambda *_:self.guard(self.aging_detail))
        for c in (self.aging_period,self.aging_role):c.currentIndexChanged.connect(lambda *_:self.guard(self.render_aging))
        self.aging_party.textChanged.connect(lambda *_:self.guard(self.render_aging));self.aging_overdue.toggled.connect(lambda *_:self.guard(self.render_aging))

    def _refresh_reporting(self):
        s=self.workspace.state
        periods=[("当前期间 / "+s.period,None)]+[(p+" 月末快照",p) for p in sorted(s.closings)]
        _options(self.balance_account,[(a.label+" / "+a.code,a.code) for a in self.workspace.accounts])
        _options(self.balance_period,periods);_options(self.aging_period,periods)
        self.render_bank_statement();self.render_aging()

    def render_bank_statement(self):
        w=self.workspace;s=w.state;account=self.balance_account.currentData();period=self.balance_period.currentData()
        editable=period is None and s.period not in s.closings and account is not None
        for control in (self.bank_closing,self.ledger_closing,self.balance_evidence,self.save_balance_button,self.adjustment_row,self.adjustment_category,self.adjustment_evidence,self.classify_button,self.unclassify_button):control.setEnabled(editable)
        self.adjustment_ids=[]
        if account is None:
            self.balance_status.setText("请先登记账户");_populate(self.balance_table,("项目","金额（元）"),[]);_populate(self.adjustment_table,("未达记录",),[]);_options(self.adjustment_row,[]);return
        selected_period=period or s.period
        if selected_period in s.closings and account not in s.closings[selected_period].get("bank_statements",{}):
            self.balance_status.setText("所选期间没有该账户的余额调节表快照")
            self.bank_closing.clear();self.ledger_closing.clear();self.balance_evidence.clear()
            _populate(self.balance_table,("项目","金额（元）"),[]);_populate(self.adjustment_table,("未达记录",),[]);_options(self.adjustment_row,[]);self._adjustment_category();return
        report=bank_statement(w,account,period)
        self.bank_closing.setText(format_amount(report["bank_minor"]) if report["bank_minor"] is not None else "")
        self.ledger_closing.setText(format_amount(report["ledger_minor"]) if report["ledger_minor"] is not None else "");self.balance_evidence.setText(report["evidence"])
        difference=format_amount(report["difference_minor"]) if report["difference_minor"] is not None else "未计算"
        self.balance_status.setText(f'{report["period"]} / {report["status"]} · 调节后差额 {difference} 元 · {report["unreviewed_count"]} 笔待复核')
        rows=[]
        for label,key in (("银行期末余额","bank_minor"),("账面期末余额","ledger_minor")):
            value=report[key];rows.append([label,format_amount(value) if value is not None else "未录入"])
        rows += [[label,format_amount(amount)] for label,amount in report["totals"].items()]
        for label,key in (("银行调节后余额","bank_adjusted_minor"),("账面调节后余额","ledger_adjusted_minor"),("调节后差额","difference_minor")):
            value=report[key];rows.append([label,format_amount(value) if value is not None else "未计算"])
        _populate(self.balance_table,("项目","金额（元）"),rows)
        self.adjustment_ids=[p["record_id"] for p in report["items"]]
        _populate(self.adjustment_table,("来源记录","金额（元）","未达类别","已复核","依据"),[[self.label(p["record_id"]),format_amount(p["amount_minor"]),p["category"],"是" if p["reviewed"] else "否",p["evidence"]] for p in report["items"]])
        _options(self.adjustment_row,[(self.label(rid),rid) for rid in self.adjustment_ids]);self._adjustment_category()

    def _adjustment_category(self):
        r=self.workspace.records.get(self.adjustment_row.currentData())
        _options(self.adjustment_category,[(x,x) for x in ((timing_category(r),"待查") if r else ())])

    def save_balances_selected(self):
        self.apply("set_closing_balances",account=self.balance_account.currentData(),bank_minor=parse_amount(self.bank_closing.text()),ledger_minor=parse_amount(self.ledger_closing.text()),evidence=self.balance_evidence.text())

    def classify_selected(self):
        self.apply("classify_unreconciled",row=self.adjustment_row.currentData(),category=self.adjustment_category.currentText(),evidence=self.adjustment_evidence.text())

    def unclassify_selected(self):
        self.apply("unclassify_unreconciled",row=self.adjustment_row.currentData(),note="人工撤销未达分类，保留操作历史")

    def render_aging(self):
        report=aging_report(self.workspace,self.aging_period.currentData());role=self.aging_role.currentData();party=self.aging_party.text().strip().casefold()
        details=[p for p in report["details"] if (not role or p["role"]==role) and (not party or party in p["party"].casefold()) and (not self.aging_overdue.isChecked() or (p["overdue_days"] or 0)>0)]
        groups=summarize_aging(details);self.aging_rows=details
        receivable=sum(p["remaining_minor"] for p in details if p["role"]=="receivable");payable=sum(p["remaining_minor"] for p in details if p["role"]=="payable")
        self.aging_status.setText(f'{report["period"]} 月末口径 / 当前筛选 {len(details)} 张未结清单据 · 应收 {format_amount(receivable)} 元 · 应付 {format_amount(payable)} 元')
        _populate(self.aging_summary_table,("类型","往来单位","未结清（元）",*AGE_BUCKETS,"已逾期（元）","未到期（元）","缺到期日（元）","单据数"),
            [[_NAMES[g["role"]],g["party"],format_amount(g["remaining_minor"]),*[format_amount(g["buckets"][k]) for k in AGE_BUCKETS],format_amount(g["overdue_minor"]),format_amount(g["not_due_minor"]),format_amount(g["due_missing_minor"]),g["count"]] for g in groups])
        _populate(self.aging_detail_table,("类型","往来单位","单据编号","单据日期","未结清（元）","账龄（天）","区间","到期日","逾期（天）","状态"),
            [[_NAMES[p["role"]],p["party"],p["reference"],p["day"],format_amount(p["remaining_minor"]),p["age_days"],p["bucket"],p["due"] or "未提供",p["overdue_days"] if p["overdue_days"] is not None else "未提供",p["status"]] for p in details])

    def adjustment_detail(self):self.show_records((self._choose(self.adjustment_table,self.adjustment_ids),))
    def aging_detail(self):self.show_records((self._choose(self.aging_detail_table,self.aging_rows)["record_id"],))
