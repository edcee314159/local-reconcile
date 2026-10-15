from .domain import Issue

def preflight(bank, ledger):
    issues = list(bank.issues + ledger.issues)
    if bank.raw.role != "bank" or ledger.raw.role != "ledger":
        issues.append(Issue("role","error","银行流水与日记账角色不正确"))
    if bank.mapping.declared_account.strip() != ledger.mapping.declared_account.strip():
        issues.append(Issue("account","error","双方声明的账户不一致"))
    if any(t.currency != "CNY" for d in (bank,ledger) for t in d.transactions):
        issues.append(Issue("currency","error","本版仅支持人民币"))
    if bank.raw.sha256 == ledger.raw.sha256:
        issues.append(Issue("same_file","warning","两侧文件内容完全相同，请检查是否选错文件"))
    for d in (bank,ledger):
        accounts = {t.account for t in d.transactions}
        if len(accounts) > 1:
            issues.append(Issue("multiple_accounts","error","文件包含多个账户"))
    if bank.transactions and ledger.transactions:
        bdays=[t.day for t in bank.transactions]; ldays=[t.day for t in ledger.transactions]
        if (min(bdays),max(bdays)) != (min(ldays),max(ldays)):
            issues.append(Issue("date_range","warning","双方日期区间不同，请留意跨期或缺失记录"))
    return tuple(issues)
