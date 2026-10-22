import json
from pathlib import Path
from .demo import make_demo
from .matching import suggest_matches
from .workspace import record_event
from .operations import open_items,suggest_transfers
from .storage import save_workspace,load_workspace,export_workspace

def run_business_smoke(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);w=make_demo()
    group=next(c for c in suggest_matches(w).candidates if len(c.left)+len(c.right)>2)
    w=record_event(w,"confirm_match",left=group.left,right=group.right,note="虚构业务复核")
    records=list(w.records.values())
    bank=next(r for r in records if r.role=="bank" and r.reference=="SET-02")
    ledger=next(r for r in records if r.role=="ledger" and r.reference=="SET-02")
    w=record_event(w,"explain",bank=bank.id,ledger=ledger.id,category="手续费",evidence="虚构结算单：20元")
    cash=next(r for r in records if r.role=="bank" and r.reference=="PAY-03")
    item=next(r for r in records if r.role=="receivable")
    w=record_event(w,"allocate",cash=cash.id,item=item.id,amount_minor=300000,note="虚构收款核实")
    out,inc=suggest_transfers(w)[0]
    w=record_event(w,"confirm_transfer",outgoing=out,incoming=inc,fee_minor=0,evidence="已核实两个虚构本企业账户")
    w=record_event(w,"close_period")
    w=record_event(w,"advance_period",period="2026-11")
    save_workspace(w,output/"business-demo.lrwork")
    restored=load_workspace(output/"business-demo.lrwork")
    if restored.state!=w.state:raise RuntimeError("business replay mismatch")
    export_workspace(w,output/"business-report.xlsx")
    result={"data":"synthetic","combination_relations":len(w.state.matches),"difference_explanations":len(w.state.explanations),
            "remaining_receivable_minor":next(i["remaining_minor"] for i in open_items(w) if i["record"].role=="receivable"),
            "internal_transfers":len(w.state.transfers),"closed_periods":len(w.state.closings)}
    result.update(_run_settlement_smoke(output))
    from .reporting_smoke import run_reporting_smoke
    result.update(run_reporting_smoke(output))
    from .commercial_demo import run_commercial_smoke
    result.update(run_commercial_smoke(output))
    from .advanced_demo import run_advanced_smoke
    result.update(run_advanced_smoke(output))
    (output/"business-smoke.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def _run_settlement_smoke(output):
    from .settlements import advance_rows
    w=make_demo();rows=list(w.records.values())
    def find(role,reference):return next(r.id for r in rows if r.role==role and r.reference==reference)
    c=next(c for c in suggest_matches(w).candidates if len(c.left)>1 and len(c.right)>1)
    w=record_event(w,"confirm_match",left=c.left,right=c.right,note="虚构多对多结算依据")
    original=find("bank","ORIG-08");item=find("receivable","INV-08")
    w=record_event(w,"allocate",cash=original,item=item,amount_minor=10000,note="虚构原核销")
    allocation=next(iter(w.state.allocations))
    w=record_event(w,"refund",original=original,cash=find("bank","REFUND-08"),amount_minor=3000,category="退款",evidence="虚构退款回单",allocation=allocation)
    prepaid=find("bank","PREPAY-09")
    w=record_event(w,"register_advance",cash=prepaid,amount_minor=10000,evidence="虚构预付协议")
    advance=next(iter(w.state.advances))
    w=record_event(w,"allocate_advance",advance=advance,item=find("payable","INV-09"),amount_minor=6000,note="虚构到货结算")
    w=record_event(w,"refund",original=prepaid,cash=find("bank","REFUND-09"),amount_minor=3000,category="退款",evidence="虚构预付款退回",advance=advance)
    path=output/"settlement-demo.lrwork";save_workspace(w,path);restored=load_workspace(path)
    if restored.state!=w.state:raise RuntimeError("settlement replay mismatch")
    export_workspace(restored,output/"settlement-report.xlsx")
    return {"many_to_many_relations":len(w.state.matches),"refunds":len(w.state.refunds),
            "advance_remaining_minor":advance_rows(w)[0]["remaining_minor"],
            "reopened_receivable_minor":next(i["remaining_minor"] for i in open_items(w) if i["record"].id==item)}
