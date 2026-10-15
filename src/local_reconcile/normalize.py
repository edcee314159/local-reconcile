from dataclasses import fields
from .domain import Dataset, Issue, Transaction, LocalReconcileError
from .amounts import parse_amount
from .dates import parse_date

def _value(row, index):
    if index is None:
        return None
    if index < 0 or index >= len(row.cells):
        return None
    c = row.cells[index]
    if c.kind == "formula":
        if c.cached_value is None:
            raise LocalReconcileError("formula_cache", "公式没有缓存值，请在表格软件重算并另存")
        return c.cached_value
    return c.value

def _text(row, index, identifier=False):
    value = _value(row, index)
    if value is None:
        return ""
    if identifier and isinstance(value, (int, float)) and not isinstance(value, bool):
        if abs(value) >= 10**15:
            raise LocalReconcileError("identifier_precision", "数字型长编号可能已丢失精度，请从原系统导出文本编号")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
    return str(value).strip()

def normalize(table, mapping):
    issues, transactions = [], []
    indices = [getattr(mapping, f.name) for f in fields(mapping) if f.name.endswith("_col")]
    valid = mapping.confirmed and mapping.declared_account.strip() and mapping.declared_currency in ("CNY", "人民币", "RMB")
    valid = valid and all(i is None or (type(i) is int and 0 <= i < len(table.headers)) for i in indices)
    dual = mapping.direction == "income_expense"
    if dual:
        valid = valid and mapping.amount_col is None and mapping.income_col is not None and mapping.expense_col is not None and mapping.income_col != mapping.expense_col
    else:
        valid = valid and mapping.direction in ("signed","inverted") and mapping.amount_col is not None and mapping.income_col is None and mapping.expense_col is None
    money_cols = [mapping.income_col,mapping.expense_col] if dual else [mapping.amount_col]
    valid = valid and mapping.date_col not in money_cols
    if not valid:
        issues.append(Issue("mapping","error","请确认字段、金额方向、人民币及同一账户声明"))
        return Dataset(table,mapping,(),tuple(issues))
    if mapping.account_col is None:
        issues.append(Issue("account_declared","warning","账户由用户声明，未从文件核验"))
    if mapping.currency_col is None:
        issues.append(Issue("currency_declared","warning","币种由用户声明，未从文件核验"))
    seen = {}
    for row in table.rows:
        if all(c.value is None or c.value == "" for c in row.cells):
            issues.append(Issue("blank_row","warning",f"第 {row.source_line} 行为空白行，保留原行", (row.id,)))
            continue
        try:
            day = parse_date(_value(row,mapping.date_col), mapping.date_format, table.excel_epoch)
            if dual:
                income = _value(row,mapping.income_col)
                expense = _value(row,mapping.expense_col)
                if income in (None,"") and expense in (None,""):
                    raise LocalReconcileError("amount_missing","收入和支出均为空，请补全金额")
                inc = 0 if income in (None,"") else parse_amount(income)
                exp = 0 if expense in (None,"") else parse_amount(expense)
                if inc < 0 or exp < 0 or (inc and exp):
                    raise LocalReconcileError("direction","收支双列应为非负值，且不可同时非零")
                cents = inc-exp
            else:
                cents = parse_amount(_value(row,mapping.amount_col))
                if mapping.direction == "inverted":
                    cents = -cents
            account = _text(row,mapping.account_col,True)
            if mapping.account_col is not None and not account:
                raise LocalReconcileError("account","账户列存在空值，请核实")
            if account and account != mapping.declared_account.strip():
                raise LocalReconcileError("account","文件账户与声明账户不一致")
            currency = _text(row,mapping.currency_col)
            if mapping.currency_col is not None and currency not in ("CNY","人民币","RMB"):
                raise LocalReconcileError("currency","文件包含非人民币或空币种")
            party = _text(row,mapping.party_col)
            reference = _text(row,mapping.reference_col,True)
            summary = _text(row,mapping.summary_col)
            transaction = Transaction(row.id,table.role,day,cents,party,reference,summary,account or mapping.declared_account.strip(),"CNY")
            transactions.append(transaction)
            key = (day,cents,party,reference,summary)
            if key in seen:
                issues.append(Issue("duplicate","warning","疑似重复记录，未删除，请复核",(seen[key],row.id)))
            seen[key] = row.id
            if not cents:
                issues.append(Issue("zero_amount","warning","零金额记录已保留",(row.id,)))
        except LocalReconcileError as error:
            issues.append(Issue(error.code,"error",f"第 {row.source_line} 行：{error}",(row.id,)))
    if not transactions and not any(i.severity=="error" for i in issues):
        issues.append(Issue("empty_data","error","没有可核对的交易"))
    return Dataset(table,mapping,tuple(transactions),tuple(issues))
