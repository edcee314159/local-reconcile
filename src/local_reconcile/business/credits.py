"""Credit adjustments reduce debt independently of cash refunds."""
from .workspace import active_records, fail, _integer, _note
from .settlements import item_used

CREDIT_ROLES = {"receivable_credit": "receivable", "payable_credit": "payable"}
CREDIT_CATEGORIES = ("红字抵减", "退货", "折让")


def credit_used(s, rid):
    return sum(p["amount_minor"] for p in s.credits.values() if p["credit"] == rid)


def credit_rows(w, state=None):
    s = state or w.state
    return [{"id": r.id, "role": r.role, "party": r.party, "reference": r.reference,
             "amount_minor": r.amount_minor, "applied_minor": credit_used(s, r.id),
             "remaining_minor": r.amount_minor-credit_used(s, r.id), "record": r}
            for r in active_records(w, s).values() if r.role in CREDIT_ROLES]


def apply_credit(w, s, e, active):
    d = e.data
    if e.kind == "undo_credit_note":
        target = d.get("target")
        _note(d, "note", True)
        if not isinstance(target, str) or target not in s.credits:
            fail("红字抵减不存在或已撤销")
        del s.credits[target]
        return
    credit, item = active.get(d.get("credit")), active.get(d.get("item"))
    amount = _integer(d.get("amount_minor"), True)
    category = d.get("category")
    evidence = _note(d, "evidence", True)
    if not credit or not item or CREDIT_ROLES.get(credit.role) != item.role or credit.party != item.party:
        fail("请选择同一单位、对应应收应付方向的红字单据和原单据")
    if credit.day < item.day:
        fail("红字、退货或折让日期不能早于原单据")
    if category not in CREDIT_CATEGORIES:
        fail("红字退货折让类别无效")
    if amount > credit.amount_minor-credit_used(s, credit.id) or amount > item.amount_minor-item_used(s, item.id):
        fail("抵减超过红字可用金额或原单据余额；已结清款项请先登记实际退款")
    s.credits[f"credit-{e.seq}"] = {"credit": credit.id, "item": item.id, "amount_minor": amount,
                                   "category": category, "evidence": evidence, "period": s.period}
