"""Explicit extra source mappings for settlement and recognition evidence."""
from .workspace import fail
from ..normalize import _value, _text
from ..dates import parse_date

SOURCE_FIELDS = {
    "settlement_line": {"settlement": ("结算批次号",True,("结算批次","结算编号","结算批次号")), "category": ("结算类别",True,("类别","结算类别")), "order": ("原订单号",False,("订单号","原订单号","订单编号"))},
    "cutoff_business": {"invoice_day": ("开票日（可选）",False,("开票日","开票日期")), "payment_day": ("收付款日（可选）",False,("收付款日","付款日期","收款日期"))},
    "cutoff_entry": {"entry": ("凭证行唯一编号",True,("凭证行编号","凭证行唯一编号","记账行号"))},
}
CATEGORIES = ("销售","退款","佣金","运费","其他扣款","其他加款")


def validate_columns(batch):
    fields=SOURCE_FIELDS.get(batch.role,{})
    if type(batch.extra_cols) is not dict or set(batch.extra_cols)-set(fields):fail("扩展字段映射无效")
    for name,(_,required,_) in fields.items():
        col=batch.extra_cols.get(name)
        if col is None:
            if required:fail("请指定扩展字段："+fields[name][0])
        elif type(col) is not int or not 0<=col<len(batch.raw.headers):fail("扩展字段列号无效")


def source_values(batch,row):
    values={}
    for name,col in batch.extra_cols.items():
        if col is None:continue
        value=_value(row,col)
        if value in (None,""):values[name]="";continue
        values[name]=parse_date(value,batch.mapping.date_format,batch.raw.excel_epoch).isoformat() if name.endswith("_day") else _text(row,col,name in ("order","settlement","entry"))
    if batch.role=="settlement_line" and (not values.get("settlement") or values.get("category") not in CATEGORIES):fail("每行须有结算批次及有效类别")
    if batch.role=="settlement_line" and values["category"] in ("销售","退款") and not values.get("order"):fail("销售及退款明细须提供原订单号")
    if batch.role=="cutoff_entry" and not values.get("entry"):fail("每条记账记录须提供凭证行唯一编号")
    return values
