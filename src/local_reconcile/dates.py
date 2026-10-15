from datetime import date, datetime
from openpyxl.utils.datetime import from_excel
from .domain import LocalReconcileError

def parse_date(value, date_format=None, excel_epoch=None) -> date:
    if isinstance(value, bool):
        raise LocalReconcileError("date", "日期类型不正确")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and excel_epoch:
        try:
            result = from_excel(value, datetime.combine(excel_epoch, datetime.min.time()))
            if isinstance(result, datetime):
                return result.date()
        except (ValueError, OverflowError):
            pass
        raise LocalReconcileError("date", "Excel 日期无效")
    if isinstance(value, str):
        formats = [date_format] if date_format else ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]
        for fmt in formats:
            try:
                return datetime.strptime(value.strip(), fmt).date()
            except (ValueError, TypeError):
                continue
    raise LocalReconcileError("date", "日期无效或顺序不明确，请选择日期格式")
