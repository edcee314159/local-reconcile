"""Atomic, replay-validated correction plans with immutable impact previews."""
from hashlib import sha256
import json
from copy import deepcopy
from .workspace import record_event,active_records,fail,_note,period_end
from ..project_store import _encode
from ..domain import LocalReconcileError,check_cancel,never_cancel
from ..amounts import format_amount

SAFE = frozenset("confirm_match reject_match undo_match undo_reject explain undo_explain register_advance allocate_advance refund undo_refund undo_advance allocate undo_allocate confirm_transfer undo_transfer set_closing_balances classify_unreconciled unclassify_unreconciled apply_credit_note undo_credit_note review_duplicate register_partner_statement decide_partner undo_partner_decision confirm_net_settlement undo_net_settlement register_cutoff_rule undo_cutoff_rule explain_cutoff undo_cutoff_explanation register_evidence_rule undo_evidence_rule link_evidence_cash undo_evidence_cash confirm_evidence_chain undo_evidence_confirmation register_contract_stage verify_stage_condition undo_stage_condition link_stage_cash undo_stage_cash undo_contract_stage exclude undo_exclude".split())


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")


def workspace_fingerprint(w):
    # Include source snapshots and mappings, not cached derived state or event count alone.
    return sha256(_canonical(_encode(w))).hexdigest()


def _plan(operations,reason):
    reason=_note({"reason":reason},"reason",True)
    if type(operations) is not list or not 1<=len(operations)<=50:fail("更正方案须包含1—50步操作")
    try:
        encoded=_canonical(operations)
        if len(encoded)>1024*1024:fail("更正方案超过1MiB限制")
        ops=json.loads(encoded)
    except (ValueError,TypeError,RecursionError):fail("更正方案格式无效")
    for op in ops:
        if type(op) is not dict or set(op)!={"kind","data"} or not isinstance(op["kind"],str) or op["kind"] not in SAFE or type(op["data"]) is not dict:fail("更正仅支持业务操作，不能修改来源、设置、期间或历史快照")
    return ops,reason


def _token(base,ops,reason):
    return sha256(_canonical([base,ops,reason])).hexdigest()


def _dependencies(w,op):
    s=w.state;k=op["kind"];t=op["data"].get("target");out=[]
    def add(kind,key,reason):out.append({"kind":kind,"target":key,"reason":reason})
    if k=="undo_allocate":
        for key,p in s.refunds.items():
            if p.get("allocation")==t:add("undo_refund",key,"原核销存在关联退款，请先复核并显式撤销")
    if k=="undo_advance":
        for name,rows in (("undo_allocate",s.allocations),("undo_refund",s.refunds)):
            for key,p in rows.items():
                if p.get("advance")==t:add(name,key,"预收预付款存在后续核销或退款")
    if k=="undo_refund" and t in s.refunds:
        p=s.refunds[t];a=s.allocations.get(p.get("allocation"),{});item=a.get("item")
        for key,q in s.credits.items():
            if item and q.get("item")==item:add("undo_credit_note",key,"退款释放的单据余额可能已用于红字抵减")
        for key,q in s.allocations.items():
            if item and key!=p.get("allocation") and q.get("item")==item:add("undo_allocate",key,"相关单据存在其他核销，请检查余额占用")
            elif p.get("advance") and q.get("advance")==p["advance"]:add("undo_allocate",key,"关联预收预付存在后续核销")
    if k=="undo_contract_stage":
        if t in s.stage_conditions:add("undo_stage_condition",t,"请先撤销阶段条件核实")
        for key,p in s.stage_cash_links.items():
            if p["stage"]==t:add("undo_stage_cash",key,"阶段存在已关联收付款")
    if k=="undo_evidence_rule" and t in s.evidence_confirmations:add("undo_evidence_confirmation",t,"请先撤销该业务证据链确认")
    return out


def _metrics(w,cancelled):
    from .settlements import item_cash_used,item_credit_used,item_used,cash_free,advance_remaining
    from .credits import credit_rows
    from .reporting import aging_report,bank_statement
    from .counterparty import counterparty_report
    from .net_settlements import net_settlement_reports
    from .cutoff import cutoff_report
    from .evidence_chain import evidence_report
    from .contract_terms import contract_report
    s=w.state;values={}
    def put(area,key,metric,value,money=False):values[area,key,metric]=format_amount(value) if money and value is not None else value
    for r in active_records(w).values():
        check_cancel(cancelled)
        if r.role in ("receivable","payable"):
            for label,value in (("未结余额（元）",r.amount_minor-item_used(s,r.id)),("现金核销（元）",item_cash_used(s,r.id)),("红字抵减（元）",item_credit_used(s,r.id))):put("应收应付",r.id,label,value,True)
        elif r.role=="bank":put("银行资金",r.id,"可核销余额（元）",cash_free(w,s,r.id),True)
    for key in s.advances:put("预收预付",key,"剩余余额（元）",advance_remaining(s,key),True)
    for row in credit_rows(w):put("红字单据",row["id"],"可用余额（元）",row["remaining_minor"],True)
    for name in ("matches","allocations","refunds","transfers","credits"):
        put("业务统计",name,"关系数量",len(getattr(s,name)))
    for p in aging_report(w)["groups"]:
        key=p["role"]+" / "+p["party"]
        for bucket,value in p["buckets"].items():put("账龄",key,bucket+"（元）",value,True)
        put("账龄",key,"逾期余额（元）",p["overdue_minor"],True)
    for a in w.accounts:
        p=bank_statement(w,a.code);put("余额调节",a.code,"状态",p["status"])
        for field in ("difference_minor","bank_adjusted_minor","ledger_adjusted_minor"):put("余额调节",a.code,field+"（元）",p[field],True)
    for key,statement in s.partner_statements.items():
        check_cancel(cancelled)
        if statement["as_of"]!=period_end(s.period).isoformat():continue
        p=counterparty_report(w,key)
        for field in ("own_total_minor","partner_total_minor","difference_minor","confirmed_count","explained_count","unreviewed_count"):
            put("双方往来",key,field,p[field],field.endswith("_minor"))
        for row in p["rows"]:
            for field in ("own_minor","partner_minor","difference_minor","status"):
                put("双方往来明细",row["id"],field,row[field],field.endswith("_minor"))
    # Stable keyed rows keep changes local and readable.
    reports=(("净到账",net_settlement_reports(w)),("月末检查",cutoff_report(w)),("证据链",evidence_report(w)))
    for area,report in reports:
        rows=report if isinstance(report,list) else next((report[k] for k in ("groups","details","businesses","rows") if isinstance(report.get(k),list)),[])
        for i,p in enumerate(rows):
            key=str(p.get("id") or p.get("business") or p.get("record_id") or json.dumps([p.get("party"),p.get("reference")],ensure_ascii=False))
            for field,value in p.items():
                if field in ("status","review_valid","flags","missing") or field.endswith("_minor"):put(area,key,field,value,field.endswith("_minor"))
    for p in contract_report(w)["stages"]:
        for field in ("paid_minor","remaining_minor","due_day","status","flags"):
            put("合同阶段",p["id"],field,p[field],field.endswith("_minor"))
    return values


def _simulate(w,ops,cancelled):
    current=w
    for op in ops:
        check_cancel(cancelled)
        current=record_event(current,op["kind"],**op["data"])
    if current.state.closings!=w.state.closings:fail("更正不能改变既有月末快照")
    return current


def preview_correction(w,operations,reason,cancelled=never_cancel):
    check_cancel(cancelled);base=workspace_fingerprint(w)
    result={"ok":False,"error":"","blockers":[],"changes":[],"base":base,"operations":[],"reason":reason,"plan_token":""}
    current=w;op=None
    try:
        ops,reason=_plan(operations,reason)
        result.update(operations=ops,reason=reason,plan_token=_token(base,ops,reason))
        for op in ops:
            check_cancel(cancelled)
            current=record_event(current,op["kind"],**op["data"])
        if current.state.closings!=w.state.closings:fail("更正不能改变既有月末快照")
        before=_metrics(w,cancelled);after=_metrics(current,cancelled)
        changes=[{"area":key[0],"key":key[1],"metric":key[2],"before":before.get(key),"after":after.get(key)} for key in sorted(before.keys()|after.keys()) if before.get(key)!=after.get(key)]
        result.update(ok=True,changes=changes)
    except LocalReconcileError as exc:
        result["error"]=str(exc)
        if op:result["blockers"]=_dependencies(current,op)
    check_cancel(cancelled)
    return result


def apply_correction(w,preview,reason):
    if type(preview) is not dict or preview.get("ok") is not True:fail("请先生成通过校验的更正预览")
    ops,reason=_plan(preview.get("operations"),reason)
    base=workspace_fingerprint(w)
    if preview.get("base")!=base or preview.get("reason")!=reason or preview.get("plan_token")!=_token(base,ops,reason):fail("工作区、方案或依据已变化，请重新预览")
    current=_simulate(w,ops,never_cancel)
    return record_event(current,"record_correction",reason=reason,base=base,operations=ops)


def record_correction_audit(w,s,e):
    ops,reason=_plan(e.data.get("operations"),e.data.get("reason"))
    base=e.data.get("base")
    if not isinstance(base,str) or len(base)!=64 or any(c not in "0123456789abcdef" for c in base):fail("更正审计指纹无效")
    # Metadata describes immediately preceding operations, it never executes them again.
    prior=w.events[e.seq-len(ops)-1:e.seq-1] if e.seq>len(ops) else ()
    if [(x.kind,x.data) for x in prior]!=[(x["kind"],x["data"]) for x in ops]:fail("更正审计与已执行操作不一致")
    # Later account/source imports are absent from historical event metadata.
    # The full base fingerprint is checked at application time, not reconstructed here.
    s.corrections[f"correction-{e.seq}"]={"reason":reason,"base":base,"operations":deepcopy(ops),"period":s.period}
