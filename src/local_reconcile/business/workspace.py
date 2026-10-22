from calendar import monthrange
from dataclasses import replace, asdict
from datetime import date
import json, re
from .models import Account, Batch, Record, Settings, Event, State, Workspace
from ..domain import LocalReconcileError
from ..normalize import normalize, _value
from ..dates import parse_date
from ..matching import stable_id

ROLES = ("bank", "ledger", "receivable", "payable", "receivable_credit", "payable_credit", "partner_receivable", "partner_payable", "settlement_order", "settlement_line", "cutoff_business", "cutoff_entry", "business_evidence")
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
    from .source_fields import validate_columns,source_values
    validate_columns(batch)
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
        if batch.role in ("receivable_credit","payable_credit") and (not t.amount_minor or not t.party or not t.reference):fail("红字退货折让须提供非零金额、往来单位和唯一单据编号")
        if batch.role in ("partner_receivable","partner_payable") and (t.amount_minor<0 or not t.party or not t.reference):fail("对方对账单须提供非负未结余额、往来单位和单据编号")
        extra=source_values(batch,rows[t.id])
        if batch.role in ("settlement_order","settlement_line","cutoff_business","cutoff_entry") and (not t.party or not t.reference):fail("新业务来源须提供单位及明确业务编号")
        if batch.role in ("settlement_order","cutoff_business") and t.amount_minor<=0:fail("订单及待核算业务金额须为正数")
        if batch.role in ("settlement_line","cutoff_entry") and not t.amount_minor:fail("结算及记账明细金额不能为零")
        if batch.role=="settlement_line" and (t.amount_minor>0)!=(extra["category"] in ("销售","其他加款")):fail("结算类别与金额正负方向不一致")
        if batch.role=="business_evidence":
            if not t.party or not t.reference:fail("业务凭证须提供单位及唯一单据编号")
            kind=extra["kind"]
            if (kind in ("合同","付款","收款","退款") and t.amount_minor<=0) or (kind=="发票" and not t.amount_minor) or (kind not in ("合同","发票","付款","收款","退款") and t.amount_minor<0):fail("合同及收付款退款须为正数，发票不能为零，其余凭证金额不能为负数")
        due=None
        if batch.due_col is not None:
            value=_value(rows[t.id],batch.due_col)
            if value not in (None,""):due=parse_date(value,m.date_format,raw.excel_epoch)
        result.append(Record(stable_id("business-row",batch.id,t.id),batch.id,t.id,batch.role,batch.account,
                             t.day,abs(t.amount_minor) if batch.role in ("receivable_credit","payable_credit") else t.amount_minor,t.party,t.reference,t.summary,due,extra))
    return result

def build_records(w):
    records={}; invoices=set()
    if len({a.code for a in w.accounts})!=len(w.accounts):fail("账户重复")
    account_ids={a.code for a in w.accounts}
    batch_ids=set()
    for b in w.batches:
        if b.id in batch_ids:fail("来源批次重复")
        batch_ids.add(b.id)
        suffix=()
        if b.statement_period is not None:
            if b.role not in ("partner_receivable","partner_payable"):fail("只有对方月末对账单允许单独记录所属月份")
            period_end(b.statement_period);suffix=(b.statement_period,)
        if b.id!=stable_id("batch",b.role,b.account,b.raw.sha256,b.raw.sheet,b.raw.header_row,*suffix):fail("来源批次标识不一致")
        if b.role in ("bank","ledger") and b.account not in account_ids:fail("来源账户未登记为本企业人民币账户")
        batch_invoices=set()
        for r in _batch_records(b):
            if r.id in records:fail("来源记录重复")
            if r.role in ("partner_receivable","partner_payable"):
                key=r.party,r.reference
                if key in batch_invoices:fail("对方对账单同一单位同一编号只能有一行未结余额")
                batch_invoices.add(key)
            if r.role in ("receivable","payable","receivable_credit","payable_credit"):
                key=r.role,r.party,r.reference
                if key in invoices:fail("同一往来单位的单据编号重复；请先整理为一张单据一行，已有单据不要再次导入")
                invoices.add(key)
            if r.role in ("settlement_order","settlement_line","cutoff_business","cutoff_entry"):
                suffix=(r.extra["settlement"],r.reference) if r.role=="settlement_line" else (r.extra["entry"],) if r.role=="cutoff_entry" else (r.reference,)
                key=(r.role,r.party,*suffix)
                if key in invoices:fail("订单、业务、结算行或凭证行唯一编号重复，请核实来源")
                invoices.add(key)
            if r.role=="business_evidence":
                key=(r.role,r.party,r.extra["direction"],r.extra["kind"],r.reference)
                if key in invoices:fail("同一单位、方向和类型的单据编号重复，请核实来源")
                invoices.add(key)
            records[r.id]=r
            if len(records)>200000:fail("工作区累计记录超过 200,000 行，请拆分工作区")
    return records

def add_batch(w,role,account,raw,mapping,due_col=None,extra_cols=None):
    statement_period=w.state.period if role in ("partner_receivable","partner_payable") else None
    suffix=(statement_period,) if statement_period else ()
    bid=stable_id("batch",role,account,raw.sha256,raw.sheet,raw.header_row,*suffix)
    if any(b.id==bid for b in w.batches):fail("同一文件、工作表、表头和账户已经导入，未重复添加")
    batch=Batch(bid,role,account,raw,mapping,due_col,statement_period,dict(extra_cols or {}))
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

def _balance_item(s,e):
    """Find the invoice whose net settled balance this event can change."""
    d=e.data
    if e.kind in ("allocate","allocate_advance","apply_credit_note"):return d.get("item")
    if e.kind=="undo_credit_note":return s.credits.get(d.get("target"),{}).get("item")
    if e.kind=="undo_allocate":return s.allocations.get(d.get("target"),{}).get("item")
    if e.kind=="refund":allocation=d.get("allocation")
    elif e.kind=="undo_refund":allocation=s.refunds.get(d.get("target"),{}).get("allocation")
    else:return None
    return s.allocations.get(allocation,{}).get("item")


def replay(w):
    from .settlements import apply_settlement, validate_balances, item_used, cash_free, occupied_settlements, advance_remaining
    from .reporting import apply_reporting, bank_statement, aging_report
    from .credits import apply_credit, credit_rows
    from .duplicates import apply_duplicate, guard_duplicate_use, duplicate_groups
    from .counterparty import apply_counterparty, counterparty_report
    from .net_settlements import apply_net_settlement, net_settlement_reports, touch_net, occupied_net
    from .cutoff import apply_cutoff, cutoff_report, touch_cutoff
    from .evidence_chain import apply_evidence,evidence_report,touch_evidence,occupied_evidence
    from .contract_terms import apply_contract,validate_stage_balances,contract_report,occupied_contracts
    period_end(w.start_period)
    settings=asdict(w.settings)
    bounds={"window_days":(0,31),"max_parts":(2,5),"max_pool":(1,16),"max_candidates":(1,100),"project_budget":(1,200000),"anchor_budget":(1,10000)}
    for k,(lo,hi) in bounds.items():
        if type(settings[k]) is not int or not lo<=settings[k]<=hi:fail("组合规则参数超出允许范围")
    s=State(w.start_period);batches={b.id:b for b in w.batches};imported=set()
    allowed={
      "confirm_net_settlement":{"group","banks","evidence"},"undo_net_settlement":{"target","note"},
      "register_cutoff_rule":{"business","method","start","end","evidence"},"undo_cutoff_rule":{"target","note"},"explain_cutoff":{"business","evidence"},"undo_cutoff_explanation":{"target","note"},
      "apply_credit_note":{"credit","item","amount_minor","category","evidence"},"undo_credit_note":{"target","note"},
      "review_duplicate":{"group","evidence"},
      "register_partner_statement":{"batch","as_of","evidence"},"decide_partner":{"batch","own","partner","kind","evidence"},"undo_partner_decision":{"target","note"},
      "import_batch":{"batch"},"confirm_match":{"left","right","note"},"reject_match":{"left","right","note"},
      "undo_match":{"target","note"},"undo_reject":{"left","right","note"},
      "explain":{"bank","ledger","category","evidence"},"undo_explain":{"target","note"},
      "register_advance":{"cash","amount_minor","evidence"},"allocate_advance":{"advance","item","amount_minor","note"},
      "refund":{"original","cash","amount_minor","category","evidence","allocation","advance"},
      "undo_refund":{"target","note"},"undo_advance":{"target","note"},
      "allocate":{"cash","item","amount_minor","note"},"undo_allocate":{"target","note"},
      "confirm_transfer":{"outgoing","incoming","fee_minor","evidence"},"undo_transfer":{"target","note"},
      "set_closing_balances":{"account","bank_minor","ledger_minor","evidence"},
      "classify_unreconciled":{"row","category","evidence"},"unclassify_unreconciled":{"row","note"},
      "close_period":{"accounts"},"advance_period":{"period"},"exclude":{"row","note"},"undo_exclude":{"row","note"}}
    allowed.update({'register_evidence_rule': {'evidence', 'group', 'contract', 'required'}, 'undo_evidence_rule': {'target', 'note'}, 'link_evidence_cash': {'evidence', 'cash', 'document', 'amount_minor'}, 'undo_evidence_cash': {'target', 'note'}, 'confirm_evidence_chain': {'evidence', 'group'}, 'undo_evidence_confirmation': {'target', 'note'}, 'register_contract_stage': {'delay_days', 'trigger', 'evidence', 'name', 'contract', 'base_day', 'amount_minor'}, 'verify_stage_condition': {'evidence', 'stage', 'document'}, 'undo_stage_condition': {'target', 'note'}, 'link_stage_cash': {'cash', 'kind', 'stage', 'evidence', 'amount_minor'}, 'undo_stage_cash': {'target', 'note'}, 'undo_contract_stage': {'target', 'note'}, 'record_correction': {'reason', 'base', 'operations'}})
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
        guard_duplicate_use(w,s,e)
        balance_item=_balance_item(s,e)
        balance_before=item_used(s,balance_item) if balance_item else None
        if e.kind=="import_batch":
            b=batches.get(d.get("batch"))
            if b is None or b.id in imported:fail("来源导入记录无效或重复")
            if b.statement_period is not None and b.statement_period!=s.period:fail("对方对账单导入月份与所属期间不一致")
            new=[r for r in w.records.values() if r.batch_id==b.id]
            if b.role not in ("partner_receivable","partner_payable","settlement_order","settlement_line","cutoff_business","cutoff_entry","business_evidence") and s.closings and any(r.day<=period_end(max(s.closings)) for r in new):fail("来源包含已结账期间记录；请另建修订工作区")
            s.visible.update(r.id for r in new);imported.add(b.id)
        elif e.kind in ('register_evidence_rule', 'undo_evidence_rule', 'link_evidence_cash', 'undo_evidence_cash', 'confirm_evidence_chain', 'undo_evidence_confirmation'):
            apply_evidence(w,s,e,active)
        elif e.kind in ('register_contract_stage', 'verify_stage_condition', 'undo_stage_condition', 'link_stage_cash', 'undo_stage_cash', 'undo_contract_stage'):
            apply_contract(w,s,e,active)
        elif e.kind=="record_correction":
            from .corrections import record_correction_audit
            record_correction_audit(w,s,e)
        elif e.kind in ("confirm_net_settlement","undo_net_settlement"):
            apply_net_settlement(w,s,e,active)
        elif e.kind in ("register_cutoff_rule","undo_cutoff_rule","explain_cutoff","undo_cutoff_explanation"):
            apply_cutoff(w,s,e,active)
        elif e.kind in ("apply_credit_note","undo_credit_note"):
            apply_credit(w,s,e,active)
        elif e.kind=="review_duplicate":
            apply_duplicate(w,s,e)
        elif e.kind in ("register_partner_statement","decide_partner","undo_partner_decision"):
            apply_counterparty(w,s,e,active)
        elif e.kind in ("set_closing_balances","classify_unreconciled","unclassify_unreconciled"):
            apply_reporting(w,s,e,active)
        elif e.kind in ("register_advance","allocate_advance","refund","undo_refund","undo_advance"):
            apply_settlement(w,s,e,active)
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
            if e.kind=="undo_allocate" and any(p.get("allocation")==target for p in s.refunds.values()):fail("请先撤销关联退款")
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
            used_item=item_used(s,item.id)
            if amount>cash_free(w,s,cash.id) or amount>item.amount_minor-used_item:fail("分配金额超过收付款可用余额或单据未结清余额")
            s.allocations[f"allocation-{e.seq}"]={"cash":cash.id,"item":item.id,"amount_minor":amount,"note":note,"period":s.period}
        elif e.kind=="confirm_transfer":
            o,i=active.get(d.get("outgoing")),active.get(d.get("incoming"));fee=_integer(d.get("fee_minor",0))
            if not o or not i or o.role!="bank" or i.role!="bank" or o.account==i.account:fail("内部转账须为本企业两个不同账户的银行记录")
            if o.amount_minor>=0 or i.amount_minor<=0 or fee<0 or -o.amount_minor!=i.amount_minor+fee:fail("转出金额应等于转入金额加已核实手续费")
            evidence=_note(d,"evidence",True)
            occupied={x for p in s.transfers.values() for x in (p["outgoing"],p["incoming"])}
            if o.id in occupied or i.id in occupied:fail("记录已参与内部转账关系")
            if occupied_settlements(s).intersection((o.id,i.id)):fail("已登记预收预付或退款的记录不能再转为内部转账")
            if any(p["cash"] in (o.id,i.id) for p in s.allocations.values()):fail("已用于往来核销的收付款不能再确认为内部转账")
            s.transfers[f"transfer-{e.seq}"]={"outgoing":o.id,"incoming":i.id,"amount_minor":i.amount_minor,"fee_minor":fee,"evidence":evidence,"period":s.period}
        elif e.kind=="close_period":
            matched=_used(s.matches)
            pending=sorted(r.id for r in active.values() if r.role in ("bank","ledger") and r.id not in matched)
            balances={r.id:r.amount_minor-item_used(s,r.id) for r in active.values() if r.role in ("receivable","payable")}
            account_codes=d.get("accounts")
            if account_codes is None:
                # Earlier formats had no account membership at closing; use only evidence visible then.
                account_codes=sorted({b.account for b in w.batches if b.id in imported and b.role in ("bank","ledger")}|set(s.closing_balances))
            if not isinstance(account_codes,list) or any(not isinstance(code,str) for code in account_codes) or len(set(account_codes))!=len(account_codes) or not set(account_codes)<={a.code for a in w.accounts}:fail("月末账户范围无效")
            statements={code:bank_statement(w,code,state=s) for code in account_codes}
            aging=aging_report(w,state=s)
            partner_reports={bid:counterparty_report(w,bid,state=s) for bid,p in s.partner_statements.items() if p["as_of"]==period_end(s.period).isoformat()}
            net_reports=net_settlement_reports(w,state=s);cutoff=cutoff_report(w,state=s)
            s.closings[s.period]={"evidence":evidence_report(w,state=s),"contracts":contract_report(w,state=s),"net_settlements":net_reports,"cutoff":cutoff,"partner_reports":partner_reports,"credit_balances":{p["id"]:p["remaining_minor"] for p in credit_rows(w,s)},"credits":dict((k,dict(v)) for k,v in s.credits.items()),"duplicate_groups":duplicate_groups(w,s),"bank_statements":statements,"aging":aging,"outstanding":pending,"open_items":balances,"matches":sorted(s.matches),"allocations":sorted(s.allocations),"transfers":sorted(s.transfers),"advances":{k:advance_remaining(s,k) for k in s.advances},"refunds":sorted(s.refunds)}
        elif e.kind in ("exclude","undo_exclude"):
            rid=d.get("row");_note(d,required=True)
            if rid not in s.visible:fail("来源行不存在")
            if e.kind=="exclude":
                if rid not in active:fail("来源行当前不可排除")
                occupied=_used(s.matches)|{x for p in s.transfers.values() for x in (p["outgoing"],p["incoming"])}|{x for p in s.allocations.values() for x in (p["cash"],p["item"])}|{x for p in s.explanations.values() for x in (p["bank"],p["ledger"])}
                occupied |= occupied_settlements(s)|occupied_net(s)|occupied_evidence(s)|occupied_contracts(s)
                occupied |= set(s.cutoff_rules)|set(s.cutoff_explanations)
                occupied |= {x for p in s.credits.values() for x in (p["credit"],p["item"])}
                occupied |= {x for p in s.partner_decisions.values() for x in (p["own"],p["partner"]) if x}
                if rid in occupied:fail("请先撤销此记录参与的业务操作")
                s.excluded.add(rid)
            else:
                if rid not in s.excluded:fail("此记录未排除")
                s.excluded.remove(rid)
        touch_net(w,s,e);touch_cutoff(w,s,e);touch_evidence(w,s,e)
        validate_balances(w,s);validate_stage_balances(w,s)
        if balance_item and item_used(s,balance_item)!=balance_before:
            s.balance_revisions[balance_item]=s.balance_revisions.get(balance_item,0)+1
    if imported!=set(batches):fail("工作区包含未经导入事件登记的来源")
    return s

def record_event(w,event_kind,**data):
    if event_kind=="close_period" and "accounts" not in data:data["accounts"]=[a.code for a in w.accounts]
    try:data=json.loads(json.dumps(data,ensure_ascii=False,allow_nan=False))
    except (ValueError,TypeError):fail("操作内容格式无效")
    updated=replace(w,events=w.events+(Event(len(w.events)+1,event_kind,data),))
    updated.__dict__["records"]=w.records
    updated.state
    return updated
