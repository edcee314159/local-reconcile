from calendar import monthrange
from dataclasses import replace, asdict
from datetime import date
import json, re
from .models import Account, Batch, Record, Settings, Event, State, Workspace
from ..domain import LocalReconcileError
from ..normalize import normalize, _value
from ..dates import parse_date
from ..matching import stable_id

ROLES = ("bank", "ledger", "receivable", "payable")
CATEGORIES = ("手续费", "折扣", "退款", "其他", "待查")

def fail(message):
    raise LocalReconcileError("business", message)

def period_end(period):
    if not isinstance(period,str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",period):
        fail("期间请使用 YYYY-MM")
    y,m=map(int,period.split("-"))
    if not 1900 <= y <= 9999:fail("期间年份须为 1900—9999")
    return date(y,m,monthrange(y,m)[1])

def new_workspace(period=None):
    period=period or date.today().strftime("%Y-%m")
    period_end(period)
    return Workspace(period)

def add_account(w,code,label):
    if not isinstance(code,str) or not code.strip() or not isinstance(label,str) or not label.strip():fail("请填写本企业人民币账户及名称")
    code,label=code.strip(),label.strip()
    if len(code)>200 or len(label)>200:fail("账户或名称过长")
    if any(a.code==code for a in w.accounts):fail("账户已经登记")
    return replace(w,accounts=w.accounts+(Account(code,label),))

def _batch_records(batch):
    if batch.role not in ROLES:fail("来源类别无效")
    raw,m=batch.raw,batch.mapping
    expected="bank" if batch.role=="bank" else "ledger"
    if raw.role != expected:fail("原始来源类别与业务类别不一致")
    if len(raw.rows)>100000 or len(raw.headers)>200:fail("单批来源超过行列限制")
    if len({r.id for r in raw.rows})!=len(raw.rows):fail("来源行标识重复")
    for r in raw.rows:
        if type(r.source_line) is not int or r.source_line<1 or len(r.cells)>200:fail("来源行无效")
        if any(isinstance(c.value,str) and len(c.value)>32767 for c in r.cells):fail("单元格文本过长")
    expected_account=batch.account if batch.role in ("bank","ledger") else "OPEN-ITEMS"
    if m.declared_account!=expected_account:fail("字段映射中的账户与所选账户不一致")
    if batch.due_col is not None and (type(batch.due_col) is not int or not 0<=batch.due_col<len(raw.headers)):fail("到期日字段无效")
    ds=normalize(raw,m)
    errors=[i.message for i in ds.issues if i.severity=="error"]
    if errors:fail("\n".join(errors[:8]))
    rows={r.id:r for r in raw.rows}
    result=[]
    for t in ds.transactions:
        if batch.role in ("receivable","payable"):
            if t.amount_minor<=0 or not t.party or not t.reference:fail("应收应付须提供正数单据金额、往来单位和唯一单据编号")
        due=None
        if batch.due_col is not None:
            value=_value(rows[t.id],batch.due_col)
            if value not in (None,""):due=parse_date(value,m.date_format,raw.excel_epoch)
        result.append(Record(stable_id("business-row",batch.id,t.id),batch.id,t.id,batch.role,batch.account,
                             t.day,t.amount_minor,t.party,t.reference,t.summary,due))
    return result

def build_records(w):
    records={}; invoices=set()
    if len({a.code for a in w.accounts})!=len(w.accounts):fail("账户重复")
    account_ids={a.code for a in w.accounts}
    batch_ids=set()
    for b in w.batches:
        if b.id in batch_ids:fail("来源批次重复")
        batch_ids.add(b.id)
        if b.id!=stable_id("batch",b.role,b.account,b.raw.sha256,b.raw.sheet,b.raw.header_row):fail("来源批次标识不一致")
        if b.role in ("bank","ledger") and b.account not in account_ids:fail("来源账户未登记为本企业人民币账户")
        for r in _batch_records(b):
            if r.id in records:fail("来源记录重复")
            if r.role in ("receivable","payable"):
                key=r.role,r.party,r.reference
                if key in invoices:fail("同一往来单位的单据编号重复；请先整理为一张单据一行，已有单据不要再次导入")
                invoices.add(key)
            records[r.id]=r
            if len(records)>200000:fail("工作区累计记录超过 200,000 行，请拆分工作区")
    return records

def add_batch(w,role,account,raw,mapping,due_col=None):
    bid=stable_id("batch",role,account,raw.sha256,raw.sheet,raw.header_row)
    if any(b.id==bid for b in w.batches):fail("同一文件、工作表、表头和账户已经导入，未重复添加")
    batch=Batch(bid,role,account,raw,mapping,due_col)
    updated=replace(w,batches=w.batches+(batch,))
    updated.records
    return record_event(updated,"import_batch",batch=bid)

def active_records(w,state=None):
    s=state or w.state;end=period_end(s.period)
    return {rid:r for rid,r in w.records.items() if rid in s.visible and rid not in s.excluded and r.day<=end}

def relation_basis(records,left,right):
    rows=[records[rid] for rid in left+right]
    refs={r.reference for r in rows if r.reference}
    parties={r.party for r in rows if r.party}
    if len(refs)==1 and all(r.reference for r in rows):
        return "共同编号",("交易对方不一致",) if len(parties)>1 else ()
    if len(refs)<=1 and len(parties)==1 and all(r.party for r in rows):
        return "同一交易对方",()
    return "人工指定",("共同编号冲突",) if len(refs)>1 else ()

def _ids(value,records,active):
    if not isinstance(value,(list,tuple)) or not value or len(value)>100:fail("每侧须选择 1—100 条记录")
    if any(not isinstance(x,str) for x in value) or len(set(value))!=len(value):fail("来源行选择重复或无效")
    if any(x not in records or x not in active for x in value):fail("记录不属于当前期间可用来源")
    return tuple(sorted(value))

def _note(data,key="note",required=False):
    value=data.get(key,"")
    if not isinstance(value,str) or len(value)>32767:fail("依据文本无效或过长")
    if required and not value.strip():fail("请填写核实依据")
    return value.strip()

def _integer(value,positive=False):
    if type(value) is not int or (positive and value<=0):fail("金额必须是有效的整数分")
    return value

def _used(relations):
    return {rid for p in relations.values() for rid in p["left"]+p["right"]}

def _match_data(w,s,data,active):
    left=_ids(data.get("left"),w.records,active);right=_ids(data.get("right"),w.records,active)
    if len(left)>1 and len(right)>1:fail("本版组合支持一对多或多对一")
    rows=[w.records[i] for i in left+right]
    if any(w.records[i].role!="bank" for i in left) or any(w.records[i].role!="ledger" for i in right):fail("对账两侧必须分别为银行流水和日记账")
    if len({r.account for r in rows})!=1:fail("跨账户记录不能确认为账面相符")
    a=sum(w.records[i].amount_minor for i in left);b=sum(w.records[i].amount_minor for i in right)
    if a!=b:fail("组合金额或收付方向不一致")
    if len(rows)>2 and (any(r.amount_minor==0 for r in rows) or len({r.amount_minor>0 for r in rows})!=1):fail("组合记录必须非零且收付方向一致")
    basis,conflicts=relation_basis(w.records,left,right)
    span=(max(r.day for r in rows)-min(r.day for r in rows)).days
    note=_note(data,required=basis=="人工指定" or bool(conflicts) or span>w.settings.window_days or max(len(left),len(right))>w.settings.max_parts)
    return {"left":left,"right":right,"amount_minor":a,"basis":basis,"conflicts":conflicts,"note":note,"period":s.period}

def replay(w):
    period_end(w.start_period)
    settings=asdict(w.settings)
    bounds={"window_days":(0,31),"max_parts":(2,5),"max_pool":(1,16),"max_candidates":(1,100),"project_budget":(1,200000),"anchor_budget":(1,10000)}
    for k,(lo,hi) in bounds.items():
        if type(settings[k]) is not int or not lo<=settings[k]<=hi:fail("组合规则参数超出允许范围")
    s=State(w.start_period);batches={b.id:b for b in w.batches};imported=set()
    allowed={
      "import_batch":{"batch"},"confirm_match":{"left","right","note"},"reject_match":{"left","right","note"},
      "undo_match":{"target","note"},"undo_reject":{"left","right","note"},
      "explain":{"bank","ledger","category","evidence"},"undo_explain":{"target","note"},
      "allocate":{"cash","item","amount_minor","note"},"undo_allocate":{"target","note"},
      "confirm_transfer":{"outgoing","incoming","fee_minor","evidence"},"undo_transfer":{"target","note"},
      "close_period":set(),"advance_period":{"period"},"exclude":{"row","note"},"undo_exclude":{"row","note"}}
    for expected,e in enumerate(w.events,1):
        if type(e.seq) is not int or e.seq!=expected or e.kind not in allowed or type(e.data) is not dict:fail("操作记录类型或序号无效")
        d=e.data
        if set(d)-allowed[e.kind]-{"legacy_sequence"}:fail("操作记录存在不支持的字段")
        if e.kind=="advance_period":
            period_end(d.get("period"))
            if d["period"]<=s.period:fail("新期间必须晚于当前期间")
            if s.period not in s.closings:fail("请先保存当前期间的月末快照")
            s.period=d["period"];continue
        if s.period in s.closings:fail("本期间已结账；请进入下一期间后记录后续处理")
        active=active_records(w,s)
        if e.kind=="import_batch":
            b=batches.get(d.get("batch"))
            if b is None or b.id in imported:fail("来源导入记录无效或重复")
            new=[r for r in w.records.values() if r.batch_id==b.id]
            if s.closings and any(r.day<=period_end(max(s.closings)) for r in new):fail("来源包含已结账期间记录；请另建修订工作区")
            s.visible.update(r.id for r in new);imported.add(b.id)
        elif e.kind in ("confirm_match","reject_match"):
            p=_match_data(w,s,d,active);key=p["left"],p["right"]
            if e.kind=="confirm_match":
                if _used(s.matches).intersection(p["left"]+p["right"]):fail("来源记录已参与已确认关系")
                s.matches[f"match-{e.seq}"]=p;s.rejected.discard(key)
            else:
                if any((v["left"],v["right"])==key for v in s.matches.values()):fail("请先撤销已确认关系")
                s.rejected.add(key)
        elif e.kind=="undo_reject":
            key=tuple(sorted(d.get("left",()))),tuple(sorted(d.get("right",())))
            if key not in s.rejected:fail("该关系没有拒绝记录")
            s.rejected.remove(key)
        elif e.kind.startswith("undo_") and e.kind not in ("undo_exclude","undo_reject"):
            group={"undo_match":s.matches,"undo_explain":s.explanations,"undo_allocate":s.allocations,"undo_transfer":s.transfers}[e.kind]
            target=d.get("target")
            if target not in group:fail("该操作已经撤销或不存在")
            _note(d);del group[target]
        elif e.kind=="explain":
            b,l=active.get(d.get("bank")),active.get(d.get("ledger"))
            if not b or not l or b.role!="bank" or l.role!="ledger" or b.account!=l.account:fail("请选择同账户的银行及账面记录")
            delta=b.amount_minor-l.amount_minor
            if not delta:fail("所选两笔没有金额差额")
            if b.amount_minor*l.amount_minor<=0:fail("相反收付方向或零金额不能仅以扣费解释")
            category=d.get("category")
            if category not in CATEGORIES:fail("差额类别无效")
            evidence=_note(d,"evidence",category!="待查")
            if any(p["bank"]==b.id and p["ledger"]==l.id for p in s.explanations.values()):fail("此差额已有说明，请先撤销旧说明")
            s.explanations[f"difference-{e.seq}"]={"bank":b.id,"ledger":l.id,"delta_minor":delta,"category":category,"evidence":evidence,"period":s.period}
        elif e.kind=="allocate":
            cash,item=active.get(d.get("cash")),active.get(d.get("item"))
            amount=_integer(d.get("amount_minor"),True)
            if not cash or not item or cash.role!="bank" or item.role not in ("receivable","payable"):fail("请选择银行收付款和应收应付单据")
            if (cash.amount_minor>0)!=(item.role=="receivable") or not cash.amount_minor:fail("收入只能核销应收，支出只能核销应付")
            if any(cash.id in (p["outgoing"],p["incoming"]) for p in s.transfers.values()):fail("内部转账不能用于往来款核销")
            note=_note(d,required=not cash.party or cash.party!=item.party)
            used_cash=sum(p["amount_minor"] for p in s.allocations.values() if p["cash"]==cash.id)
            used_item=sum(p["amount_minor"] for p in s.allocations.values() if p["item"]==item.id)
            if amount>abs(cash.amount_minor)-used_cash or amount>item.amount_minor-used_item:fail("分配金额超过收付款可用余额或单据未结清余额")
            s.allocations[f"allocation-{e.seq}"]={"cash":cash.id,"item":item.id,"amount_minor":amount,"note":note,"period":s.period}
        elif e.kind=="confirm_transfer":
            o,i=active.get(d.get("outgoing")),active.get(d.get("incoming"));fee=_integer(d.get("fee_minor",0))
            if not o or not i or o.role!="bank" or i.role!="bank" or o.account==i.account:fail("内部转账须为本企业两个不同账户的银行记录")
            if o.amount_minor>=0 or i.amount_minor<=0 or fee<0 or -o.amount_minor!=i.amount_minor+fee:fail("转出金额应等于转入金额加已核实手续费")
            evidence=_note(d,"evidence",True)
            occupied={x for p in s.transfers.values() for x in (p["outgoing"],p["incoming"])}
            if o.id in occupied or i.id in occupied:fail("记录已参与内部转账关系")
            if any(p["cash"] in (o.id,i.id) for p in s.allocations.values()):fail("已用于往来核销的收付款不能再确认为内部转账")
            s.transfers[f"transfer-{e.seq}"]={"outgoing":o.id,"incoming":i.id,"amount_minor":i.amount_minor,"fee_minor":fee,"evidence":evidence,"period":s.period}
        elif e.kind=="close_period":
            matched=_used(s.matches)
            pending=sorted(r.id for r in active.values() if r.role in ("bank","ledger") and r.id not in matched)
            balances={r.id:r.amount_minor-sum(p["amount_minor"] for p in s.allocations.values() if p["item"]==r.id) for r in active.values() if r.role in ("receivable","payable")}
            s.closings[s.period]={"outstanding":pending,"open_items":balances,"matches":sorted(s.matches),"allocations":sorted(s.allocations),"transfers":sorted(s.transfers)}
        elif e.kind in ("exclude","undo_exclude"):
            rid=d.get("row");_note(d,required=True)
            if rid not in s.visible:fail("来源行不存在")
            if e.kind=="exclude":
                if rid not in active:fail("来源行当前不可排除")
                occupied=_used(s.matches)|{x for p in s.transfers.values() for x in (p["outgoing"],p["incoming"])}|{x for p in s.allocations.values() for x in (p["cash"],p["item"])}|{x for p in s.explanations.values() for x in (p["bank"],p["ledger"])}
                if rid in occupied:fail("请先撤销此记录参与的业务操作")
                s.excluded.add(rid)
            else:
                if rid not in s.excluded:fail("此记录未排除")
                s.excluded.remove(rid)
    if imported!=set(batches):fail("工作区包含未经导入事件登记的来源")
    return s

def record_event(w,kind,**data):
    try:data=json.loads(json.dumps(data,ensure_ascii=False,allow_nan=False))
    except (ValueError,TypeError):fail("操作内容格式无效")
    updated=replace(w,events=w.events+(Event(len(w.events)+1,kind,data),))
    updated.__dict__["records"]=w.records
    updated.state
    return updated
