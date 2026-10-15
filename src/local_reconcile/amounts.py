"""Strict conversion to integer cents; never round an input silently."""
import re
from decimal import Decimal, InvalidOperation
from .domain import LocalReconcileError

_PATTERN = re.compile(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?\Z")

def parse_amount(value: str | int | float) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise LocalReconcileError("amount", "金额缺失或类型不正确")
    text = str(value).strip()
    for prefix in ("￥", "¥"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    if not _PATTERN.fullmatch(text) or (negative and text.startswith(("+", "-"))):
        raise LocalReconcileError("amount", "金额格式错误，须为最多两位小数的人民币金额")
    try:
        amount = Decimal(text.replace(",", ""))
        sign,digits,exponent=amount.as_tuple()
        coefficient=int("".join(map(str,digits)))
        cents=coefficient*(10**(exponent+2))
        if sign:cents=-cents
    except (InvalidOperation, ValueError, OverflowError):
        raise LocalReconcileError("amount", "金额无法解析") from None
    return -cents if negative else cents

def format_amount(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"{sign}{value // 100:,}.{value % 100:02d}"
