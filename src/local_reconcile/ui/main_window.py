from __future__ import annotations
from pathlib import Path
from dataclasses import replace
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QMainWindow,QWidget,QFrame,QVBoxLayout,QHBoxLayout,QLabel,
 QPushButton,QStackedWidget,QFileDialog,QMessageBox,QProgressBar,QInputDialog,QDialog,QDialogButtonBox,QComboBox,QFormLayout,QLineEdit)
from .import_page import ImportPage
from .results_page import ResultsPage
from .workers import JobRunner
from ..domain import MatchConfig,ProjectSnapshot,ReviewEvent,LocalReconcileError
from ..importers import read_table,inspect_file
from ..normalize import normalize
from ..preflight import preflight
from ..matching import reconcile
from ..review import apply_review,confirm_batch
from ..project_store import save_project,load_project
from ..export_xlsx import export_report
from ..amounts import format_amount

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle("本地对账工作台 · Local Reconcile");self.resize(1440,960);self.setMinimumSize(1120,820)
        self.snapshot=None;self.project_path=None;self.dirty=False;self.busy=False;self.job_id=0
        self.runner=JobRunner(self);self.runner.progress.connect(self._progress)
        root=QWidget();root.setObjectName("root");self.setCentralWidget(root);outer=QHBoxLayout(root);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName("sidebar");sidebar.setFixedWidth(208);side=QVBoxLayout(sidebar);side.setContentsMargins(21,32,21,24);side.setSpacing(12)
        brand=QLabel("本地对账");brand.setObjectName("brand");side.addWidget(brand)
        sub=QLabel("LOCAL RECONCILE\n公开测试版  ·  0.2.0");sub.setObjectName("sideSub");side.addWidget(sub);side.addSpacing(30)
        self.home_nav=self._nav("工作台首页",lambda:self.go(0));self.import_nav=self._nav("01  导入与字段",lambda:self._edit_import())
        self.results_nav=self._nav("02  核对与复核",lambda:self.go(2));self.results_nav.setEnabled(False)
        for button in (self.home_nav,self.import_nav,self.results_nav):side.addWidget(button)
        self.business_button=QPushButton("03  业务核算");self.business_button.setObjectName("nav");self.business_button.clicked.connect(self.open_business);side.addWidget(self.business_button)
        self.business_window=None
        side.addStretch()
        for text in ("●  全程本地处理","人民币 · 单账户 · 逐笔","保留来源，人工确认"):
            l=QLabel(text);l.setObjectName("sideHint");side.addWidget(l)
        outer.addWidget(sidebar)
        content=QWidget();body=QVBoxLayout(content);body.setContentsMargins(30,26,30,18);body.setSpacing(16)
        top=QHBoxLayout();labels=QVBoxLayout();eyebrow=QLabel("LOCAL FIRST  /  可追溯的表格核对");eyebrow.setObjectName("eyebrow");labels.addWidget(eyebrow)
        self.heading=QLabel("每一笔，都有依据。");self.heading.setObjectName("heading");labels.addWidget(self.heading);top.addLayout(labels);top.addStretch()
        self.demo_button=QPushButton("使用虚构示例");self.open_button=QPushButton("打开项目")
        self.save_button=QPushButton("保存项目");self.export_button=QPushButton("导出 Excel");self.export_button.setObjectName("primary")
        for b in (self.demo_button,self.open_button,self.save_button,self.export_button):top.addWidget(b)
        body.addLayout(top)
        self.stack=QStackedWidget();self.stack.addWidget(self._home());self.import_page=ImportPage();self.stack.addWidget(self.import_page);self.results_page=ResultsPage();self.stack.addWidget(self.results_page);body.addWidget(self.stack,1)
        progress_row=QHBoxLayout();self.progress_label=QLabel("准备就绪 · 数据仅在本机处理");self.progress_label.setObjectName("muted");progress_row.addWidget(self.progress_label,1)
        self.progress_bar=QProgressBar();self.progress_bar.setFixedWidth(190);self.progress_bar.setTextVisible(False);self.progress_bar.hide();progress_row.addWidget(self.progress_bar)
        self.cancel_button=QPushButton("取消任务");self.cancel_button.setObjectName("small");self.cancel_button.hide();progress_row.addWidget(self.cancel_button);body.addLayout(progress_row);outer.addWidget(content,1)
        self.demo_button.clicked.connect(self._demo_clicked);self.open_button.clicked.connect(self._open_clicked);self.save_button.clicked.connect(self._save_clicked);self.export_button.clicked.connect(self._export_clicked)
        self.cancel_button.clicked.connect(self.cancel_job);self.import_page.run_button.clicked.connect(self.run_reconciliation)
        self.results_page.confirm_button.clicked.connect(lambda:self.review_selection("confirm"));self.results_page.reject_button.clicked.connect(lambda:self.review_selection("reject"));self.results_page.undo_button.clicked.connect(lambda:self.review_selection("undo"));self.results_page.manual_button.clicked.connect(self._manual_pair)
        for panel in (self.import_page.bank,self.import_page.ledger):
            panel.choose.connect(self._choose_source);panel.reload.connect(self._reload_source)
        self.go(0);self._buttons()
    def open_business(self):
        from .business_window import BusinessWindow
        if self.business_window is None:self.business_window=BusinessWindow(self)
        self.business_window.show();self.business_window.raise_();self.business_window.activateWindow()

    def _nav(self,label,callback):
        b=QPushButton(label);b.setObjectName("nav");b.setCheckable(True);b.clicked.connect(callback);return b
    def _home(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(20)
        hero=QFrame();hero.setObjectName("hero");box=QVBoxLayout(hero);box.setContentsMargins(34,32,34,30);box.setSpacing(16)
        tag=QLabel("为财务人员准备的本地工作台");tag.setObjectName("eyebrow");box.addWidget(tag)
        title=QLabel("把两张表，\n核对成一份清楚的结果。");title.setObjectName("heroTitle");box.addWidget(title)
        desc=QLabel("导入银行流水与银行日记账，查看候选和差异。\n每一条关系保留原始行，确认之后再导出。");desc.setObjectName("heroText");desc.setWordWrap(True);box.addWidget(desc)
        row=QHBoxLayout();start=QPushButton("新建一次核对  →");start.setObjectName("primary");start.clicked.connect(lambda:self._edit_import());demo=QPushButton("先用虚构数据体验");demo.clicked.connect(self._demo_clicked)
        row.addWidget(start);row.addWidget(demo);row.addStretch();box.addLayout(row);layout.addWidget(hero)
        row=QHBoxLayout();row.setSpacing(16)
        for n,title,text in (("01","确认输入","选择文件、字段和收付方向。\n异常数据在预检中明确列出。"),("02","复核依据","正常候选、歧义和差异分开展示。\n确认、拒绝、撤销都有记录。"),("03","导出归档","一份报告保留原始明细和来源。\n保存项目后随时继续复核。")):
            card=QFrame();card.setObjectName("card");b=QVBoxLayout(card);b.setContentsMargins(22,22,22,22);num=QLabel(n);num.setObjectName("eyebrow");b.addWidget(num);l=QLabel(title);l.setObjectName("cardTitle");b.addWidget(l);l=QLabel(text);l.setObjectName("muted");l.setWordWrap(True);b.addWidget(l);row.addWidget(card)
        layout.addLayout(row)
        note=QLabel("本版范围：Excel / CSV、单账户人民币、逐笔核对。组合收付款与跨期事项留给人工复核。\n公开测试版已设计合成案例验证；真实企业适用性仍需实际使用反馈。");note.setObjectName("muted");note.setWordWrap(True);layout.addWidget(note);layout.addStretch();return page
    def go(self,index):
        self.stack.setCurrentIndex(index)
        for n,b in enumerate((self.home_nav,self.import_nav,self.results_nav)):b.setChecked(n==index)
        self.heading.setText(("每一笔，都有依据。","先确认输入，再开始核对。","看清差异，留下复核依据。")[index])
    def _buttons(self):
        for b in (self.demo_button,self.open_button,self.import_page.run_button):b.setEnabled(not self.busy)
        self.save_button.setEnabled(self.snapshot is not None and not self.busy);self.export_button.setEnabled(self.snapshot is not None and not self.busy)
        self.results_nav.setEnabled(self.snapshot is not None)
        self.results_page.setEnabled(not self.busy);self.import_page.setEnabled(not self.busy)
        self.progress_bar.setVisible(self.busy);self.cancel_button.setVisible(self.busy)
    def _progress(self,stage,current,total):
        self.progress_label.setText(stage+(f" · {current:,} / {total:,}" if total else f" · {current:,}" if current else ""))
        self.progress_bar.setRange(0,total if total else 0)
        if total:self.progress_bar.setValue(current)
    def _start(self,work,done):
        self.job_id+=1;self.busy=True;self._buttons();self.progress_bar.setRange(0,0);self.progress_label.setText("正在处理…")
        def success(result):
            self.busy=False;self.progress_label.setText("处理完成 · 原始文件保持不变");self._buttons();done(result);self._buttons()
        def error(exc):
            self.busy=False;self._buttons();self._error(exc)
        self.runner.submit(self.job_id,work,success,error)
    def cancel_job(self):
        self.runner.cancel(self.job_id);self.busy=False;self._buttons();self.progress_label.setText("任务已取消 · 保留上一次完整结果")
    def _error(self,error):
        self.progress_label.setText("操作未完成 · 请检查输入")
        if isinstance(error,LocalReconcileError):message=str(error)
        else:message="操作未完成，请检查文件与设置后重试。"
        QMessageBox.warning(self,"请检查",message)
    def _discard_ok(self):
        if not self.dirty:return True
        result=QMessageBox.question(self,"项目尚未保存","当前复核结果尚未保存，是否放弃并继续？",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        return result==QMessageBox.Yes
    def _demo_clicked(self):
        if self._discard_ok():self.load_demo()
    def load_demo(self):
        resource=Path(__file__).resolve().parents[1]/"resources"
        def work(progress,cancel):
            return (read_table(resource/"demo_bank.csv","bank",progress=progress,cancelled=cancel),read_table(resource/"demo_ledger.csv","ledger",progress=progress,cancelled=cancel))
        def loaded(tables):
            self.snapshot=None;self.dirty=False;self.project_path=None
            self.import_page.bank.set_table(tables[0],resource/"demo_bank.csv")
            self.import_page.ledger.set_table(tables[1],resource/"demo_ledger.csv")
            self.import_page.account.setText("SYNTHETIC-001");self.import_page.confirm_box.setChecked(False);self.go(1)
            self.progress_label.setText("已载入虚构示例 · 请核实字段与方向并勾选确认")
        self._start(work,loaded)
    def _choose_source(self,role):
        if not self._discard_ok():return
        path,_=QFileDialog.getOpenFileName(self,"选择银行流水" if role=="bank" else "选择银行日记账","","表格 (*.xlsx *.csv)")
        if path:self.load_source(role,Path(path))
    def _reload_source(self,role):
        panel=getattr(self.import_page,role)
        if panel.path:self.load_source(role,panel.path,panel.sheet_combo.currentText() if panel.sheet_combo.currentText()!="CSV" else None,panel.header_spin.value())
    def load_source(self,role,path,sheet=None,header=1):
        def work(progress,cancel):
            sheets=inspect_file(path,role);return read_table(path,role,sheet,header,progress,cancel),sheets
        def loaded(value):
            self.snapshot=None;self.project_path=None;self.dirty=False
            getattr(self.import_page,role).set_table(value[0],Path(path),value[1]);self.import_page.invalidate();self.go(1)
        self._start(work,loaded)
    def run_reconciliation(self):
        try:
            page=self.import_page
            if page.bank.table is None or page.ledger.table is None:raise LocalReconcileError("input","请先导入两份文件")
            bm=page.bank.mapping(page.account.text(),page.confirm_box.isChecked());lm=page.ledger.mapping(page.account.text(),page.confirm_box.isChecked())
            config=MatchConfig(page.tolerance.value());bt=page.bank.table;lt=page.ledger.table
            def work(progress,cancel):
                progress("标准化与预检",0,0);bank=normalize(bt,bm);ledger=normalize(lt,lm)
                issues=preflight(bank,ledger);errors=[i for i in issues if i.severity=="error"]
                if errors:raise LocalReconcileError("preflight","\n".join(i.message for i in errors[:12])+("\n另有更多异常，请修正后重试" if len(errors)>12 else ""))
                return ProjectSnapshot(1,bank,ledger,config,reconcile(bank,ledger,config,progress,cancel))
            def done(snapshot):
                self.snapshot=snapshot;self.dirty=True;self.project_path=None;self.results_page.render(snapshot);self.go(2)
            self._start(work,done)
        except LocalReconcileError as error:self._error(error)
    def _edit_import(self):
        if self.snapshot is not None:
            if not self.begin_new_run(allow_discard=self._discard_ok()):return
        self.go(1)
    def begin_new_run(self,allow_discard=False):
        if self.snapshot is not None and not allow_discard:return False
        self.snapshot=None;self.dirty=False;self.project_path=None;self.import_page.invalidate();self._buttons();return True
    def review_selection(self,kind):
        if self.snapshot is None:return
        try:
            ids=self.results_page.selected_candidates()
            if not ids:raise LocalReconcileError("selection","请先选中候选行")
            candidates=self.results_page.action_candidates
            updated=self.snapshot
            if kind=="confirm" and len(ids)>1:
                amount=sum(next(t.amount_minor for t in updated.bank.transactions if t.id==candidates[cid].bank_id) for cid in ids)
                reply=QMessageBox.question(self,"批量确认",f"即将确认 {len(ids)} 个所选候选，银行净额 {format_amount(amount)} 元。\n仅无歧义、无冲突的强依据候选可以批量确认。",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
                if reply!=QMessageBox.Yes:return
                updated=confirm_batch(updated,ids)
            else:
                for cid in ids:
                    c=candidates[cid];note=""
                    if kind=="confirm" and c.conflicts:
                        note,ok=QInputDialog.getText(self,"存在字段冲突","请核实原始记录并填写确认依据：")
                        if not ok:return
                    updated=apply_review(updated,ReviewEvent(len(updated.review.events)+1,kind,c.bank_id,c.ledger_id,note))
            self.snapshot=updated;self.dirty=True;self.results_page.render(updated);self._buttons()
        except LocalReconcileError as error:self._error(error)
    def _manual_pair(self):
        if self.snapshot is None:return
        dialog=QDialog(self);dialog.setWindowTitle("手工指定一对一关系");dialog.resize(650,230);form=QFormLayout(dialog)
        bank=QComboBox();ledger=QComboBox()
        for combo,ds in ((bank,self.snapshot.bank),(ledger,self.snapshot.ledger)):
            for t in ds.transactions:combo.addItem(f"{t.day}  {format_amount(t.amount_minor)}  {t.party}  {t.reference}  [{t.id[:8]}]",t.id)
        note=QLineEdit();note.setPlaceholderText("填写支持这两笔属于同一业务的核实依据")
        form.addRow("银行记录",bank);form.addRow("日记账记录",ledger);form.addRow("确认依据",note)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec()==QDialog.Accepted:
            try:
                if not note.text().strip():raise LocalReconcileError("manual_reason","手工指定请填写依据")
                self.snapshot=apply_review(self.snapshot,ReviewEvent(len(self.snapshot.review.events)+1,"confirm",bank.currentData(),ledger.currentData(),note.text()))
                self.dirty=True;self.results_page.render(self.snapshot);self._buttons()
            except LocalReconcileError as error:self._error(error)
    def save_to(self,path):
        if self.snapshot is None:raise LocalReconcileError("project","当前没有可保存的核对")
        save_project(self.snapshot,path);self.project_path=Path(path);self.dirty=False;self.progress_label.setText("项目已保存 · 文件包含本次输入快照与人工复核记录");self._buttons()
    def _save_clicked(self):
        if self.snapshot is None:return
        path=self.project_path
        if path is None:
            reply=QMessageBox.information(self,"本地项目文件","项目包含银行流水与日记账快照，未加密。请选择合适的本地目录。",QMessageBox.Ok|QMessageBox.Cancel)
            if reply!=QMessageBox.Ok:return
            name,_=QFileDialog.getSaveFileName(self,"保存本地项目","核对项目.lrproj","核对项目 (*.lrproj)")
            if not name:return
            path=Path(name)
        try:self.save_to(path)
        except LocalReconcileError as error:self._error(error)
    def open_from(self,path):
        def done(snapshot):
            self.snapshot=snapshot;self.project_path=Path(path);self.dirty=False;self.results_page.render(snapshot);self.go(2)
        self._start(lambda progress,cancel:load_project(path),done)
    def _open_clicked(self):
        if not self._discard_ok():return
        name,_=QFileDialog.getOpenFileName(self,"打开本地项目","","核对项目 (*.lrproj)")
        if name:self.open_from(name)
    def export_to(self,path):
        snapshot=self.snapshot
        if snapshot is None:raise LocalReconcileError("export","当前没有可导出的核对")
        self._start(lambda progress,cancel:export_report(snapshot,path,cancel),lambda result:self.progress_label.setText("Excel 报告已导出 · 已确认、差异与原始明细均保留"))
    def _export_clicked(self):
        if self.snapshot is None:return
        name,_=QFileDialog.getSaveFileName(self,"导出核对报告","核对报告.xlsx","Excel 工作簿 (*.xlsx)")
        if name:self.export_to(name)
    def can_close(self,choice):
        if not self.dirty:return True
        if choice=="discard":return True
        if choice=="save" and self.project_path is not None:
            self.save_to(self.project_path);return True
        return False
    def closeEvent(self,event):
        if self.business_window is not None and self.business_window.isVisible():
            if not self.business_window.close():event.ignore();return
        if self.dirty:
            answer=QMessageBox.question(self,"尚未保存","保存当前核对项目后退出？",QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel,QMessageBox.Cancel)
            if answer==QMessageBox.Save:
                self._save_clicked()
                if self.dirty:event.ignore();return
            elif answer!=QMessageBox.Discard:event.ignore();return
        self.runner.shutdown();event.accept()
