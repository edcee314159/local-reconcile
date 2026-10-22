"""Synthetic net-settlement and month-end accounting examples."""
from dataclasses import replace
from .demo import _raw
from .workspace import new_workspace,add_account,add_batch,record_event
from .net_settlements import net_settlement_reports
from .cutoff import cutoff_report
from ..domain import MappingSpec


def advanced_demo():
    w=add_account(new_workspace("2026-10"),"DEMO-N","虚构结算银行")
    inputs=[
        ("settlement_order",[["2026-10-01","100","虚构平台","ORDER-N1","原订单总额"]],{}),
        ("settlement_line",[["2026-10-15","100","虚构平台","SALE-1","销售结算","PAY-N1","销售","ORDER-N1"],
                            ["2026-10-15","-5","虚构平台","RETURN-1","部分退款","PAY-N1","退款","ORDER-N1"],
                            ["2026-10-15","-2","虚构平台","FEE-1","平台佣金","PAY-N1","佣金",""],
                            ["2026-10-15","-1","虚构平台","FEE-2","仓配运费","PAY-N1","运费",""]],{"settlement":5,"category":6,"order":7}),
        ("bank",[["2026-10-16","92","虚构平台","PAY-N1","结算后净到账"]],{}),
        ("cutoff_business",[["2026-10-28","100","虚构供应商","ACCEPT-1","验收100元，当前仅记70元","2026-11-05","2026-11-10"],
                            ["2026-10-01","1200","虚构服务商","SERVICE-1","12个月服务，金额口径已人工确认","2026-10-01","2026-10-01"],
                            ["2026-10-25","50","虚构待核实单位","UNREVIEWED-1","待财务确认归属规则","",""]],{"invoice_day":5,"payment_day":6}),
        ("cutoff_entry",[["2026-10-30","70","虚构供应商","ACCEPT-1","已登记部分","VOUCHER-01-1"],
                         ["2026-10-31","100","虚构服务商","SERVICE-1","本月服务归属","VOUCHER-01-2"],
                         ["2026-10-31","25","虚构待查单位","UNKNOWN-BUSINESS","缺少对应业务依据","VOUCHER-01-3"],
                         ["2026-11-02","30","虚构供应商","ACCEPT-1","下月才登记的部分","VOUCHER-02-1"]],{"entry":5}),
    ]
    for n,(role,rows,extra) in enumerate(inputs):
        account="DEMO-N" if role=="bank" else ""
        raw=_raw("bank" if role=="bank" else "ledger",f"虚构创新-{n}-{role}.csv",rows)
        extras=("结算批次号","结算类别","原订单号") if role=="settlement_line" else ("开票日","收付款日") if role=="cutoff_business" else ("凭证行唯一编号",) if role=="cutoff_entry" else ()
        raw=replace(raw,headers=raw.headers+extras)
        mapping=MappingSpec(party_col=2,reference_col=3,summary_col=4,declared_account=account or "OPEN-ITEMS",confirmed=True)
        w=add_batch(w,role,account,raw,mapping,extra_cols=extra)
    lookup={r.reference:r.id for r in w.records.values() if r.role=="cutoff_business"}
    w=record_event(w,"register_cutoff_rule",business=lookup["ACCEPT-1"],method="once",start="2026-10-28",end="2026-10-28",evidence="虚构财务确认：按验收业务发生日归属，金额口径一致")
    w=record_event(w,"register_cutoff_rule",business=lookup["SERVICE-1"],method="monthly",start="2026-10-01",end="2027-09-30",evidence="虚构人工确认：1200元服务总额，12个月按月平均归属")
    return w


def run_advanced_smoke(output):
    from .storage import save_workspace,load_workspace,export_workspace
    w=advanced_demo();net=net_settlement_reports(w)[0]
    banks=[r.id for r in w.records.values() if r.role=="bank"]
    w=record_event(w,"confirm_net_settlement",group=net["id"],banks=banks,evidence="虚构结算单逐项与银行92元核对")
    row=next(p for p in cutoff_report(w)["rows"] if p["reference"]=="ACCEPT-1")
    w=record_event(w,"explain_cutoff",business=row["business"],evidence="虚构核查：剩余30元下月记录，本期仍需财务判断处理")
    oldnet=net_settlement_reports(w);oldcutoff=cutoff_report(w)
    w=record_event(w,"close_period");w=record_event(w,"advance_period",period="2026-11")
    if net_settlement_reports(w,"2026-10")!=oldnet or cutoff_report(w,"2026-10")!=oldcutoff:raise RuntimeError("advanced history changed")
    path=output/"advanced-demo.lrwork";save_workspace(w,path)
    restored=load_workspace(path)
    if restored.state!=w.state:raise RuntimeError("advanced replay mismatch")
    export_workspace(restored,output/"advanced-report.xlsx")
    return {"net_settlement_minor":oldnet[0]["net_minor"],"net_settlement_confirmed":oldnet[0]["review_valid"],
            "cutoff_missing_minor":-row["delta_minor"],"cutoff_monthly_minor":next(p["expected_minor"] for p in oldcutoff["rows"] if p["reference"]=="SERVICE-1"),
            "cutoff_unmatched_postings":sum(not p["business"] for p in oldcutoff["rows"]),"advanced_history_preserved":True}
