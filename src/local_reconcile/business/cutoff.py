"""Evidence-backed recognition schedules and posting cut-off checks; no posting inference."""
from collections import defaultdict
from copy import deepcopy
from datetime import date
import json
from ..matching import stable_id
from .workspace import active_records, period_end, _note, fail


def _key(record):
    return stable_id("cutoff-business", record.party, record.reference)


def touch_cutoff(w, s, e):
    """Advance source revisions even when an exclusion is subsequently restored."""
    if e.kind == "import_batch":
        changed = (r for r in w.records.values() if r.batch_id == e.data.get("batch"))
    elif e.kind in ("exclude", "undo_exclude"):
        r = w.records.get(e.data.get("row"))
        changed = (r,) if r else ()
    else:
        return
    keys = {_key(r) for r in changed if r.role in ("cutoff_business", "cutoff_entry")}
    for key in keys:
        s.cutoff_versions[key] = s.cutoff_versions.get(key, 0) + 1


def _iso(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        result = date.fromisoformat(value)
        if result.isoformat() != value or result.year < 1900:
            raise ValueError
        return result
    except ValueError:
        fail("归属日期请使用 1900—9999 年的 YYYY-MM-DD")


def _month(day):
    return day.year * 12 + day.month - 1


def _business(active, value):
    record = active.get(value) if isinstance(value, str) else None
    if record is None or record.role != "cutoff_business":
        fail("请选择当前可用的业务记录")
    return record


def _through(record, rule, through):
    """Cumulative expected integer cents through a date, without floating point."""
    start, end = date.fromisoformat(rule["start"]), date.fromisoformat(rule["end"])
    if through < start:
        return 0
    if through >= end:
        return record.amount_minor
    if rule["method"] == "once":
        return record.amount_minor
    if rule["method"] == "daily":
        return record.amount_minor * ((through - start).days + 1) // ((end - start).days + 1)
    count = _month(end) - _month(start) + 1
    elapsed = min(count, _month(through) - _month(start) + 1)
    each, remainder = divmod(record.amount_minor, count)
    return each * elapsed + min(remainder, elapsed)


def _fingerprint(s, record, rule, entries):
    return stable_id("cutoff-review", s.period, record.id, record.day.isoformat(), record.amount_minor,
                     json.dumps(record.extra, ensure_ascii=False, sort_keys=True), rule["seq"],
                     s.cutoff_versions.get(_key(record), 0),
                     *(f"{r.id}:{r.day.isoformat()}:{r.amount_minor}" for r in entries))


def apply_cutoff(w, s, e, active):
    d = e.data
    if e.kind == "register_cutoff_rule":
        record = _business(active, d.get("business"))
        method = d.get("method")
        if method not in ("once", "monthly", "daily"):
            fail("归属方法须为一次确认、按月或按日分摊")
        start, end = _iso(d.get("start")), _iso(d.get("end"))
        if end < start or _month(end) - _month(start) + 1 > 1200:
            fail("归属范围须按日期顺序且不超过 1200 个月")
        if method == "once" and not (start == end == record.day):
            fail("一次确认须使用业务来源的验收或发生日期")
        evidence = _note(d, "evidence", True)
        s.cutoff_rules[record.id] = {"business": record.id, "method": method,
            "start": start.isoformat(), "end": end.isoformat(), "evidence": evidence,
            "seq": e.seq, "period": s.period}
    elif e.kind == "undo_cutoff_rule":
        target = d.get("target")
        if not isinstance(target, str) or target not in s.cutoff_rules:
            fail("归属规则不存在或已撤销")
        if target in s.cutoff_explanations:
            fail("请先撤销该业务的差异说明")
        _note(d, "note", True)
        del s.cutoff_rules[target]
    elif e.kind == "explain_cutoff":
        record = _business(active, d.get("business"))
        rule = s.cutoff_rules.get(record.id)
        if not rule:
            fail("请先登记并核实业务归属规则")
        evidence = _note(d, "evidence", True)
        entries = sorted((r for r in active.values() if r.role == "cutoff_entry" and
                          (r.party, r.reference) == (record.party, record.reference)), key=lambda r: r.id)
        s.cutoff_explanations[record.id] = {"business": record.id, "evidence": evidence,
            "period": s.period, "fingerprint": _fingerprint(s, record, rule, entries), "seq": e.seq}
    elif e.kind == "undo_cutoff_explanation":
        target = d.get("target")
        if not isinstance(target, str) or target not in s.cutoff_explanations:
            fail("差异说明不存在或已撤销")
        _note(d, "note", True)
        del s.cutoff_explanations[target]
    else:
        fail("不支持的归属核对操作")


def cutoff_report(w, period=None, state=None):
    s = state or w.state
    period = period or s.period
    if period in s.closings:
        stored = s.closings[period].get("cutoff")
        if stored is None:
            fail("所选期间没有月末核算历史快照")
        return deepcopy(stored)
    if period != s.period:
        fail("只可查看当前期间或已保存的历史期间")
    end = period_end(period)
    start = end.replace(day=1)
    # 1900 is the supported minimum, so the preceding day remains representable.
    prior_end = date.fromordinal(start.toordinal() - 1)
    active = active_records(w, s)
    businesses = {}
    postings = defaultdict(list)
    for r in active.values():
        if r.role == "cutoff_business":
            businesses[r.party, r.reference] = r
        elif r.role == "cutoff_entry":
            postings[r.party, r.reference].append(r)
    rows = []
    for party, reference in sorted(set(businesses) | set(postings)):
        record = businesses.get((party, reference))
        entries = sorted(postings[party, reference], key=lambda r: r.id)
        actual = sum(r.amount_minor for r in entries if r.day >= start)
        prior_actual = sum(r.amount_minor for r in entries if r.day < start)
        rule = s.cutoff_rules.get(record.id) if record else None
        expected = prior_expected = delta = prior_delta = None
        flags = []
        invoice = record.extra.get("invoice_day", "") if record else ""
        payment = record.extra.get("payment_day", "") if record else ""
        if rule:
            prior_expected = _through(record, rule, prior_end)
            expected = _through(record, rule, end) - prior_expected
            delta, prior_delta = actual - expected, prior_actual - prior_expected
            if delta < 0:
                flags.append("本期少记")
            elif delta > 0:
                flags.append("本期多记")
            if prior_delta:
                flags.append("以前期间差异")
            for day, flag in ((invoice, "开票跨期"), (payment, "收付款跨期")):
                if day and not rule["start"][:7] <= day[:7] <= rule["end"][:7]:
                    flags.append(flag)
        if actual + prior_actual < 0:
            flags.append("累计记账为负")
        explanation = s.cutoff_explanations.get(record.id) if record else None
        valid = bool(explanation and rule and explanation["fingerprint"] == _fingerprint(s, record, rule, entries))
        if not record:
            status = "记账记录未关联业务"
        elif not rule:
            status = "归属规则待确认"
        elif explanation and not valid:
            status = "依据或金额已变化需复核"
        elif valid:
            status = "差异已说明仍待复核"
        elif flags:
            status = "存在待复核项目"
        else:
            status = "核对一致"
        rows.append({"business": record.id if record else "", "party": party, "reference": reference,
            "method": rule["method"] if rule else "", "start": rule["start"] if rule else "",
            "end": rule["end"] if rule else "", "expected_minor": expected, "actual_minor": actual,
            "delta_minor": delta, "prior_delta_minor": prior_delta, "prior_actual_minor": prior_actual,
            "prior_expected_minor": prior_expected, "status": status, "flags": tuple(flags),
            "entries": tuple(r.id for r in entries), "invoice_day": invoice, "payment_day": payment,
            "evidence": rule["evidence"] if rule else "", "explanation": explanation["evidence"] if explanation else "",
            "explanation_valid": valid})
    return {"period": period, "rows": rows}
