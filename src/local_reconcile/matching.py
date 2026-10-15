"""Deterministic suggestions. Never confirms a match or drops a source row."""
from collections import defaultdict, Counter
from datetime import timedelta
from hashlib import sha256
from itertools import chain
from .domain import (Candidate, Difference, AmbiguityGroup, MatchResult,
                     LocalReconcileError, check_cancel, quiet_progress, never_cancel)
from .preflight import preflight

def stable_id(*parts):
    return sha256("|".join(map(str,parts)).encode("utf-8")).hexdigest()[:24]

def reconcile(bank, ledger, config, progress=quiet_progress, cancelled=never_cancel):
    if type(config.date_tolerance_days) is not int or not 0 <= config.date_tolerance_days <= 31 or type(config.max_pairs_per_group) is not int or not 1 <= config.max_pairs_per_group <= 100:
        raise LocalReconcileError("config","日期容差须为 0—31 天，候选展开上限须为 1—100")
    issues = preflight(bank, ledger)
    if any(i.severity == "error" for i in issues):
        raise LocalReconcileError("preflight","预检未通过，请先修正输入问题")
    check_cancel(cancelled)
    by_ref_amount_day, by_ref = defaultdict(list), defaultdict(list)
    by_day, by_party, empty_ref_day, empty_ref_party = (defaultdict(list) for _ in range(4))
    for t in ledger.transactions:
        by_day[t.amount_minor,t.day].append(t)
        by_party[t.amount_minor,t.day,t.party].append(t)
        if t.reference:
            by_ref_amount_day[t.reference,t.amount_minor,t.day].append(t)
            by_ref[t.reference].append(t)
        else:
            empty_ref_day[t.amount_minor,t.day].append(t)
            empty_ref_party[t.amount_minor,t.day,t.party].append(t)
    bank_ref_counts = Counter((t.reference,t.amount_minor,t.day) for t in bank.transactions)
    bank_fallback_counts = Counter((t.amount_minor,t.day,t.party,bool(t.reference)) for t in bank.transactions)
    differences, capped = {}, {}
    components = _CandidateComponents(config.max_pairs_per_group)
    limit = config.max_pairs_per_group

    def add_capped(key, bank_id, ledger_rows, reason):
        if key not in capped:
            capped[key] = [set(), tuple(t.id for t in ledger_rows), reason]
        capped[key][0].add(bank_id)

    for n,b in enumerate(bank.transactions):
        check_cancel(cancelled)
        if n % 250 == 0:
            progress("生成候选",n,len(bank.transactions))
        if b.reference:
            strong = list(chain.from_iterable(by_ref_amount_day.get((b.reference,b.amount_minor,b.day+timedelta(days=d)),()) for d in range(-config.date_tolerance_days,config.date_tolerance_days+1) if date_offset_valid(b.day,d)))
            if len(strong) * bank_ref_counts[b.reference,b.amount_minor,b.day] > limit:
                add_capped(("reference",b.reference,b.amount_minor,b.day), b.id,strong,"同编号同金额候选超过展开上限，逐笔关系尚未确定")
            else:
                for l in strong:
                    conflicts = ("party",) if b.party and l.party and b.party != l.party else ()
                    cid = stable_id("1",b.id,l.id)
                    components.add(Candidate(cid,b.id,l.id,"reference",conflicts))
            refs = by_ref.get(b.reference,())
            if len(refs) <= limit:
                for l in refs:
                    if b.amount_minor != l.amount_minor and b.amount_minor*l.amount_minor > 0 and abs((b.day-l.day).days) <= config.date_tolerance_days:
                        differences[b.id,l.id] = Difference(b.id,l.id,b.amount_minor-l.amount_minor,"共同编号一致，金额不同")
        index_day = empty_ref_day if b.reference else by_day
        index_party = empty_ref_party if b.reference else by_party
        if b.party:
            sources = (index_party.get((b.amount_minor,b.day,b.party),()),index_party.get((b.amount_minor,b.day,""),()))
        else:
            sources = (index_day.get((b.amount_minor,b.day),()),)
        count = sum(len(s) for s in sources)
        if count * bank_fallback_counts[b.amount_minor,b.day,b.party,bool(b.reference)] > limit:
            add_capped(("date",b.amount_minor,b.day), b.id,by_day[b.amount_minor,b.day],"同额同日范围候选过多，分组仅表示待进一步复核，未穷尽逐笔关系")
            continue
        for l in chain.from_iterable(sources):
            if b.reference and l.reference:
                continue
            cid = stable_id("1",b.id,l.id)
            rule = "party_date" if b.party and l.party else "date_only"
            components.add(Candidate(cid,b.id,l.id,rule))
    groups = [AmbiguityGroup(stable_id("cap",*key),tuple(sorted(v[0])),tuple(sorted(v[1])),True,v[2]) for key,v in capped.items()]
    candidates, component_groups = components.finish()
    groups.extend(component_groups)
    progress("核对完成",len(bank.transactions),len(bank.transactions))
    return MatchResult("1",tuple(sorted(candidates.values(),key=lambda c:c.id)),
                       tuple(differences[k] for k in sorted(differences)),
                       tuple(sorted(groups,key=lambda g:g.id)),issues)

def date_offset_valid(day, offset):
    try:
        day + timedelta(days=offset)
        return True
    except OverflowError:
        return False



class _CandidateComponents:
    """Bound stored edges for the entire connected ambiguity component.

    Wildcard counterparties and overlapping date windows can join many small
    cohorts. Unioning before keeping edges prevents those cohorts bypassing
    the configured expansion limit.
    """
    def __init__(self, limit):
        self.limit = limit
        self.parent = {}
        self.size = {}
        self.edges = {}
        self.truncated = set()

    def find(self, node):
        if node not in self.parent:
            self.parent[node] = node
            self.size[node] = 1
            self.edges[node] = {}
        root = node
        while root != self.parent[root]:
            root = self.parent[root]
        while node != root:
            parent = self.parent[node]
            self.parent[node] = root
            node = parent
        return root

    def add(self, candidate):
        a = self.find(("bank", candidate.bank_id))
        b = self.find(("ledger", candidate.ledger_id))
        if a != b:
            if self.size[a] < self.size[b]:
                a, b = b, a
            self.parent[b] = a
            self.size[a] += self.size.pop(b)
            other = self.edges.pop(b)
            if a in self.truncated or b in self.truncated:
                self.truncated.discard(b)
                self.truncated.add(a)
                self.edges[a].clear()
            else:
                self.edges[a].update(other)
        if a not in self.truncated:
            self.edges[a][candidate.id] = candidate
            if len(self.edges[a]) > self.limit:
                self.edges[a].clear()
                self.truncated.add(a)

    def finish(self):
        members = defaultdict(lambda: ([], []))
        for role, row_id in self.parent:
            root = self.find((role, row_id))
            members[root][0 if role == "bank" else 1].append(row_id)
        candidates, groups = {}, []
        for root, (bank_ids, ledger_ids) in members.items():
            truncated = root in self.truncated
            candidates.update(self.edges[root])
            if truncated or len(bank_ids) > 1 or len(ledger_ids) > 1:
                bs, ls = tuple(sorted(bank_ids)), tuple(sorted(ledger_ids))
                reason = ("关联候选总数超过展开上限，保留全组来源记录供人工复核"
                          if truncated else "存在多个候选，需人工决定")
                groups.append(AmbiguityGroup(stable_id("component", *bs, "/", *ls),
                                            bs, ls, truncated, reason))
        return candidates, groups
