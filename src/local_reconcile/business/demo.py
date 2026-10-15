"""Synthetic examples covering the five business workflows."""
from hashlib import sha256
from ..domain import RawTable,RawRow,RawCell,MappingSpec
from ..matching import stable_id
from .workspace import new_workspace,add_account,add_batch

def _raw(role,name,rows):
    text="\n".join(",".join(row) for row in rows)
    digest=sha256(text.encode("utf-8")).hexdigest()
    return RawTable(role,name,digest,None,1,None,("日期","金额","交易对方","共同编号","摘要"),
        tuple(RawRow(stable_id(name,i),i+2,tuple(RawCell(v) for v in row)) for i,row in enumerate(rows)))

def make_demo():
    w=add_account(new_workspace("2026-10"),"DEMO-A","虚构银行账户 A")
    w=add_account(w,"DEMO-B","虚构银行账户 B")
    inputs=[
      ("bank","DEMO-A",[
        ["2026-10-15","10000","虚构客户甲","BATCH-01","两笔合并到账"],
        ["2026-10-16","9980","虚构客户乙","SET-02","结算单扣费20元"],
        ["2026-10-17","3000","虚构客户丙","PAY-03","分期收款"],
        ["2026-10-18","-2000","虚构供应商丁","PAY-04","部分付款"],
        ["2026-10-19","-5000","内部划转","TR-01","转入虚构账户B"],
        ["2026-10-20","600","虚构客户戊","WAIT-01","待下期核实"]]),
      ("ledger","DEMO-A",[
        ["2026-10-15","6000","虚构客户甲","BATCH-01","组成明细1"],
        ["2026-10-15","4000","虚构客户甲","BATCH-01","组成明细2"],
        ["2026-10-16","10000","虚构客户乙","SET-02","扣费前应结算额"],
        ["2026-10-17","3000","虚构客户丙","PAY-03","收款记账"],
        ["2026-10-18","-2000","虚构供应商丁","PAY-04","付款记账"],
        ["2026-10-19","-5000","内部划转","TR-01","转出记账"]]),
      ("bank","DEMO-B",[["2026-10-20","5000","内部划转","TR-01","收到虚构账户A转款"]]),
      ("ledger","DEMO-B",[["2026-10-20","5000","内部划转","TR-01","转入记账"]]),
      ("receivable","",[["2026-10-01","10000","虚构客户丙","INV-03","应收单据"]]),
      ("payable","",[["2026-10-01","7000","虚构供应商丁","PUR-04","应付单据"]])]
    for role,account,rows in inputs:
        raw=_raw("bank" if role=="bank" else "ledger",f"虚构-{role}-{account or '往来'}.csv",rows)
        m=MappingSpec(party_col=2,reference_col=3,summary_col=4,declared_account=account or "OPEN-ITEMS",confirmed=True)
        w=add_batch(w,role,account,raw,m)
    return w
