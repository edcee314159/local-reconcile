"""Period-end reconciliation and net open-item aging; no posting or inferred balances."""
from copy import deepcopy
from collections import defaultdict
from .workspace import active_records,period_end,_used,_integer,_note,fail
from .settlements import item_used, item_cash_used, item_credit_used

TIMING_CATEGORIES=("银行已收企业未收","银行已付企业未付","企业已收银行未收","企业已付银行未付")
AGE_BUCKETS=("0—30天","31—60天","61—90天","90天以上")


def timing_category(r):
    return TIMING_CATEGORIES[(0 if r.role=="bank" else 2)+(0 if r.amount_minor>0 else 1)]


def apply_reporting(w,s,e,active):
    d=e.data
    if e.kind=="set_closing_balances":
        account=d.get("account")
        if not isinstance(account,str) or account not in {a.code for a in w.accounts}:fail("请选择已登记的本企业人民币账户")
        s.closing_balances[account]={"bank_minor":_integer(d.get("bank_minor")),"ledger_minor":_integer(d.get("ledger_minor")),"evidence":_note(d,"evidence",True),"period":s.period}
    elif e.kind=="classify_unreconciled":
        r=active.get(d.get("row"));category=d.get("category")
        if not r or r.role not in ("bank","ledger") or not r.amount_minor or r.id in _used(s.matches):fail("请选择尚未核对相符的非零银行或账面记录")
        if category not in (timing_category(r),"待查"):fail("未达分类与来源或收付方向不一致")
        s.unreconciled_classes[r.id]={"category":category,"evidence":_note(d,"evidence",True),"period":s.period}
    else:
        rid=d.get("row");_note(d,"note",True)
        if rid not in s.unreconciled_classes:fail("该记录尚无未达分类")
        del s.unreconciled_classes[rid]


def bank_statement(w,account,period=None,state=None):
    s=state or w.state;period=period or s.period
    if period in s.closings:
        stored=s.closings[period].get("bank_statements",{}).get(account)
        if stored is None:fail("所选期间没有该账户的余额调节表快照")
        return deepcopy(stored)
    if period!=s.period:fail("只可查看当前期间或已保存的历史期间")
    if account not in {a.code for a in w.accounts}:fail("账户不存在")
    used=_used(s.matches);items=[];totals={k:0 for k in TIMING_CATEGORIES};unreviewed=0
    for r in active_records(w,s).values():
        if r.account!=account or r.role not in ("bank","ledger") or r.id in used:continue
        classification=s.unreconciled_classes.get(r.id,{})
        category=classification.get("category","待查")
        reviewed=category==timing_category(r) and bool(r.amount_minor)
        if reviewed:totals[category]+=abs(r.amount_minor)
        else:unreviewed+=1
        items.append({"record_id":r.id,"role":r.role,"amount_minor":r.amount_minor,"category":category,"evidence":classification.get("evidence",""),"reviewed":reviewed})
    balances=s.closing_balances.get(account)
    # Closing balances belong to one period only; never silently carry them to a new month.
    if balances and balances["period"]!=period:balances=None
    bank=balances["bank_minor"] if balances else None;ledger=balances["ledger_minor"] if balances else None
    adjusted_bank=bank+totals["企业已收银行未收"]-totals["企业已付银行未付"] if balances else None
    adjusted_ledger=ledger+totals["银行已收企业未收"]-totals["银行已付企业未付"] if balances else None
    difference=adjusted_bank-adjusted_ledger if balances else None
    status="未录入期末余额" if not balances else "存在待复核项目" if unreviewed else "调节后相符" if difference==0 else "调节后仍有差额"
    return {"period":period,"account":account,"bank_minor":bank,"ledger_minor":ledger,"bank_adjusted_minor":adjusted_bank,"ledger_adjusted_minor":adjusted_ledger,"difference_minor":difference,"totals":totals,"unreviewed_count":unreviewed,"status":status,"evidence":balances["evidence"] if balances else "","items":sorted(items,key=lambda p:p["record_id"])}


def summarize_aging(details):
    groups={}
    for p in details:
        key=p["role"],p["party"]
        if key not in groups:groups[key]={"role":key[0],"party":key[1],"remaining_minor":0,"buckets":{k:0 for k in AGE_BUCKETS},"overdue_minor":0,"due_missing_minor":0,"not_due_minor":0,"count":0}
        g=groups[key];amount=p["remaining_minor"];g["remaining_minor"]+=amount;g["buckets"][p["bucket"]]+=amount;g["count"]+=1
        if p["overdue_days"] is None:g["due_missing_minor"]+=amount
        elif p["overdue_days"]>0:g["overdue_minor"]+=amount
        else:g["not_due_minor"]+=amount
    return [groups[k] for k in sorted(groups)]


def aging_report(w,period=None,state=None):
    s=state or w.state;period=period or s.period
    if period in s.closings:
        stored=s.closings[period].get("aging")
        if stored is None:fail("所选期间没有账龄分析快照")
        return deepcopy(stored)
    if period!=s.period:fail("只可查看当前期间或已保存的历史期间")
    end=period_end(period);details=[]
    for r in active_records(w,s).values():
        if r.role not in ("receivable","payable"):continue
        allocated=item_cash_used(s,r.id);credited=item_credit_used(s,r.id);remaining=r.amount_minor-item_used(s,r.id)
        if remaining<=0:continue
        age=(end-r.day).days;bucket=AGE_BUCKETS[0 if age<=30 else 1 if age<=60 else 2 if age<=90 else 3]
        overdue=max(0,(end-r.due).days) if r.due else None
        details.append({"record_id":r.id,"role":r.role,"party":r.party,"reference":r.reference,"day":r.day.isoformat(),"due":r.due.isoformat() if r.due else "","amount_minor":r.amount_minor,"allocated_minor":allocated,"credited_minor":credited,"remaining_minor":remaining,"age_days":age,"bucket":bucket,"overdue_days":overdue,"status":"未提供到期日" if overdue is None else "已逾期" if overdue else "未逾期"})
    details.sort(key=lambda p:(p["role"],p["party"],p["day"],p["record_id"]))
    return {"period":period,"as_of":end.isoformat(),"details":details,"groups":summarize_aging(details)}
