"""Cross-batch warnings retain source rows and require evidence before reuse."""
from collections import defaultdict
from .workspace import active_records, fail, _note
from ..matching import stable_id


def duplicate_groups(w, state=None):
    s = state or w.state
    strong, weak = defaultdict(list), defaultdict(list)
    active = active_records(w, s)
    for r in active.values():
        if r.role not in ("bank", "ledger"):
            continue
        if r.reference:
            strong[r.role, r.account, r.reference, r.amount_minor, r.party].append(r)
        weak[r.role, r.account, r.day, r.amount_minor, r.party].append(r)
    groups, seen = [], set()
    for basis, buckets in (("同账户、同编号、同金额、同单位", strong), ("同账户、同日期、同金额、同单位且存在缺失编号", weak)):
        for rows in buckets.values():
            if buckets is weak and all(r.reference for r in rows):
                continue
            if len({r.batch_id for r in rows}) < 2:
                continue
            ids = tuple(sorted(r.id for r in rows))
            if ids in seen:
                continue
            seen.add(ids)
            key = stable_id("duplicate", *ids)
            decision = s.duplicate_decisions.get(key)
            reviewed = bool(decision and tuple(decision["rows"]) == ids)
            groups.append({"id": key, "rows": ids, "basis": basis,
                           "status": "已确认为独立业务" if reviewed else "待复核",
                           "evidence": decision["evidence"] if reviewed else ""})
    return sorted(groups, key=lambda p: p["id"])


def pending_duplicate_rows(w, s):
    return {rid for p in duplicate_groups(w, s) if p["status"] == "待复核" for rid in p["rows"]}


def apply_duplicate(w, s, e):
    evidence = _note(e.data, "evidence", True)
    group = next((p for p in duplicate_groups(w, s) if p["id"] == e.data.get("group")), None)
    if group is None:
        fail("疑似重复组不存在或来源已变化，请重新复核")
    s.duplicate_decisions[group["id"]] = {"rows": group["rows"], "evidence": evidence, "period": s.period}


def guard_duplicate_use(w, s, e):
    keys = {"link_evidence_cash": ("cash",), "link_stage_cash": ("cash",), "confirm_net_settlement": ("banks",), "confirm_match": ("left", "right"), "allocate": ("cash",),
            "register_advance": ("cash",), "allocate_advance": ("advance",), "refund": ("original", "cash"),
            "confirm_transfer": ("outgoing", "incoming"), "classify_unreconciled": ("row",),
            "explain": ("bank", "ledger")}.get(e.kind)
    if not keys:
        return
    selected = set()
    for key in keys:
        value = e.data.get(key)
        if isinstance(value, str): selected.add(value)
        elif isinstance(value, (tuple, list)): selected.update(x for x in value if isinstance(x, str))
    if e.kind == "allocate_advance":
        selected = {s.advances[key]["cash"] for key in selected if key in s.advances}
    if selected & pending_duplicate_rows(w, s):
        fail("所选来源疑似跨批次重复，请先排除重复行或凭依据确认为独立业务")
