"""Flat, formula-safe report rows for settlements and recognition checks."""
from .net_settlements import net_settlement_reports
from .cutoff import cutoff_report
from ..amounts import format_amount
from ..domain import check_cancel

HEADERS={
 "净到账还原汇总":["期间","组编号","单位","结算批次","销售（元）","退款（元）","费用扣款（元）","其他加款（元）","应到账（元）","银行净额（元）","差异（元）","状态","待核实问题","确认依据"],
 "结算组成明细":["期间","组编号","来源行","日期","单位","结算批次","结算行号","类别","原订单号","金额（元）","文件","源行"],
 "结算订单核验":["期间","组编号","订单号","订单来源","订单金额（元）","累计销售结算（元）","累计退款（元）","未结算订单额（元）"],
 "结算到账流水":["期间","组编号","银行来源","账户","日期","金额（元）","文件","源行","确认依据"],
 "月末核算检查":["期间","单位","业务编号","业务来源","归属方法","开始日","结束日","本期应归属（元）","本期已记账（元）","本期差异（元）","前期应归属（元）","前期已记账（元）","前期差异（元）","状态","检查提示","开票日","收付款日","归属规则依据","差异说明","说明有效"],
 "核算记账依据":["期间","业务编号","单位","来源类别","来源记录","日期","金额（元）","凭证行唯一号","文件","源行"]}


def export_advanced(w,s,put,cancelled):
    batches={b.id:b for b in w.batches};raws={b.id:{r.id:r for r in b.raw.rows} for b in w.batches}
    def source(rid):
        r=w.records[rid];b=batches[r.batch_id]
        return r,b.raw.filename,raws[b.id][r.source_id].source_line
    def money(value):return format_amount(value) if value is not None else "未确认"
    periods=sorted(s.closings)
    if s.period not in periods:periods.append(s.period)
    for period in periods:
        check_cancel(cancelled)
        reports=s.closings[period].get("net_settlements",[]) if period in s.closings else net_settlement_reports(w,state=s)
        cutoff=s.closings[period].get("cutoff",{"rows":[]}) if period in s.closings else cutoff_report(w,state=s)
        for p in reports:
            check_cancel(cancelled)
            put("净到账还原汇总",[period,p["id"],p["party"],p["settlement"],money(p["income_minor"]),money(p["refund_minor"]),money(p["fee_minor"]),money(p["other_minor"]),money(p["net_minor"]),money(p["bank_minor"]),money(p["difference_minor"]),p["status"],"；".join(p["issues"]),p["evidence"]])
            for rid in p["rows"]:
                r,file,line=source(rid);put("结算组成明细",[period,p["id"],rid,r.day,r.party,r.extra["settlement"],r.reference,r.extra["category"],r.extra.get("order",""),money(r.amount_minor),file,line])
            for c in p["order_checks"]:put("结算订单核验",[period,p["id"],c["reference"],c["record"],money(c["order_minor"]),money(c["settled_minor"]),money(c["refunded_minor"]),money(c["remaining_minor"])])
            for rid in p["banks"]:
                r,file,line=source(rid);put("结算到账流水",[period,p["id"],rid,r.account,r.day,money(r.amount_minor),file,line,p["evidence"]])
        for p in cutoff["rows"]:
            check_cancel(cancelled)
            put("月末核算检查",[period,p["party"],p["reference"],p["business"],p["method"],p["start"],p["end"],money(p["expected_minor"]),money(p["actual_minor"]),money(p["delta_minor"]),money(p.get("prior_expected_minor")),money(p.get("prior_actual_minor")),money(p["prior_delta_minor"]),p["status"],"；".join(p["flags"]),p["invoice_day"],p["payment_day"],p["evidence"],p["explanation"],"是" if p["explanation_valid"] else "否"])
            for rid in ([p["business"]] if p["business"] else [])+list(p["entries"]):
                r,file,line=source(rid);put("核算记账依据",[period,p["reference"],p["party"],r.role,rid,r.day,money(r.amount_minor),r.extra.get("entry",""),file,line])
