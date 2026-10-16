"""Synthetic, independently balanced period-end example for frozen-app checks."""
from dataclasses import replace
from .demo import _raw
from ..domain import MappingSpec
from .workspace import new_workspace,add_account,add_batch,record_event
from .reporting import bank_statement,aging_report,timing_category
from .storage import save_workspace,load_workspace,export_workspace


def reporting_demo():
    w=add_account(new_workspace("2026-10"),"REPORT-DEMO","虚构月末账户")
    inputs=[("bank",[["2026-10-10","100","虚构客户","B1","银行代收"],["2026-10-11","-20","虚构供应商","B2","银行代付"]]),
            ("ledger",[["2026-10-12","50","虚构客户","L1","在途收款"],["2026-10-13","-10","虚构供应商","L2","在途付款"]]),
            ("receivable",[["2026-07-01","100","虚构客户","INV-AGING","逾期应收","2026-10-15"]]),
            ("payable",[["2026-10-20","80","虚构供应商","INV-PAY","到期未提供",""]])]
    for role,rows in inputs:
        account="REPORT-DEMO" if role in ("bank","ledger") else ""
        raw=_raw("bank" if role=="bank" else "ledger",f"虚构月末-{role}.csv",rows)
        if role in ("receivable","payable"):raw=replace(raw,headers=raw.headers+("到期日",))
        m=MappingSpec(party_col=2,reference_col=3,summary_col=4,declared_account=account or "OPEN-ITEMS",confirmed=True)
        w=add_batch(w,role,account,raw,m,due_col=5 if role in ("receivable","payable") else None)
    # Synthetic statement balances: 1000 +50 -10 = 960 +100 -20 =1040.
    w=record_event(w,"set_closing_balances",account="REPORT-DEMO",bank_minor=100000,ledger_minor=96000,evidence="虚构银行对账单及期末账簿")
    for r in w.records.values():
        if r.role in ("bank","ledger"):w=record_event(w,"classify_unreconciled",row=r.id,category=timing_category(r),evidence="虚构回单核实未达性质")
    return w


def run_reporting_smoke(output):
    w=reporting_demo();old=bank_statement(w,"REPORT-DEMO");aging=aging_report(w)
    w=record_event(w,"close_period");w=record_event(w,"advance_period",period="2026-11")
    w=record_event(w,"set_closing_balances",account="REPORT-DEMO",bank_minor=200000,ledger_minor=200000,evidence="虚构下月余额")
    path=output/"closing-demo.lrwork";save_workspace(w,path);restored=load_workspace(path)
    if restored.state!=w.state:raise RuntimeError("reporting replay mismatch")
    preserved=bank_statement(restored,"REPORT-DEMO","2026-10")==old
    if not preserved:raise RuntimeError("historical balance report changed")
    export_workspace(restored,output/"closing-report.xlsx")
    g=next(g for g in aging["groups"] if g["role"]=="receivable")
    return {"bank_adjustment_difference_minor":old["difference_minor"],"aging_receivable_minor":g["remaining_minor"],"aging_overdue_minor":g["overdue_minor"],"historical_adjustment_preserved":preserved}
