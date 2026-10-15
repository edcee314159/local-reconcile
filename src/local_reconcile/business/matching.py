from collections import defaultdict
from itertools import combinations
from .models import Suggestion, LimitedRange, Analysis
from .workspace import active_records, relation_basis
from ..matching import stable_id
from ..domain import check_cancel, never_cancel, quiet_progress

class _Components:
    def __init__(self,limit):
        self.limit=limit;self.parent={};self.size={};self.edges={};self.reasons={}
    def find(self,x):
        if x not in self.parent:self.parent[x]=x;self.size[x]=1;self.edges[x]={};self.reasons[x]=set()
        root=x
        while self.parent[root]!=root:root=self.parent[root]
        while x!=root:parent=self.parent[x];self.parent[x]=root;x=parent
        return root
    def union(self,a,b):
        a,b=self.find(a),self.find(b)
        if a==b:return a
        if self.size[a]<self.size[b]:a,b=b,a
        self.parent[b]=a;self.size[a]+=self.size.pop(b)
        self.edges[a].update(self.edges.pop(b));self.reasons[a].update(self.reasons.pop(b))
        self.bound(a);return a
    def bound(self,root):
        if len(self.edges[root])>self.limit:self.reasons[root].add("完整关联组候选超过展开上限")
        if self.reasons[root]:self.edges[root].clear()
    def add(self,c):
        nodes=c.left+c.right;root=self.find(nodes[0])
        for x in nodes[1:]:root=self.union(root,x)
        if not self.reasons[root]:self.edges[root][c.id]=c
        self.bound(root)
    def limited(self,nodes,reason):
        if not nodes:return
        root=self.find(nodes[0])
        for x in nodes[1:]:root=self.union(root,x)
        self.reasons[root].add(reason);self.bound(root)
    def finish(self):
        members=defaultdict(list)
        for x in self.parent:members[self.find(x)].append(x)
        candidates={};ranges=[]
        for root,nodes in members.items():
            if self.reasons[root]:ranges.append(LimitedRange(tuple(sorted(nodes)),"；".join(sorted(self.reasons[root]))))
            else:candidates.update(self.edges[root])
        return Analysis(tuple(sorted(candidates.values(),key=lambda c:c.id)),
                        tuple(sorted(ranges,key=lambda r:r.rows)))

def suggest_matches(w,progress=quiet_progress,cancelled=never_cancel):
    check_cancel(cancelled)
    records=active_records(w);settings=w.settings
    sides={"bank":[],"ledger":[]};index=defaultdict(list)
    for r in records.values():
        if r.role not in sides:continue
        sides[r.role].append(r)
        sign=(r.amount_minor>0)-(r.amount_minor<0)
        if r.reference:index[r.role,r.account,sign,"ref",r.reference].append(r)
        if r.party:index[r.role,r.account,sign,"party",r.party].append(r)
        for mode,include in (("all",True),("empty_ref",not r.reference),
                             ("empty_party",not r.party),("empty_both",not r.reference and not r.party)):
            if include:index[r.role,r.account,sign,"weak",r.day,r.amount_minor,mode].append(r)
    graph=_Components(settings.max_candidates);count=0;cached={};range_heads={}
    anchors=sorted(sides["bank"]+sides["ledger"],key=lambda r:r.id)
    for n,anchor in enumerate(anchors):
        check_cancel(cancelled)
        if n%100==0:progress("组合对账",n,len(anchors))
        opposite="ledger" if anchor.role=="bank" else "bank"
        sign=(anchor.amount_minor>0)-(anchor.amount_minor<0)
        key=(opposite,anchor.account,sign,anchor.reference,anchor.party,anchor.day,abs(anchor.amount_minor))
        if key not in cached:
            possible={}
            mode="empty_both" if anchor.reference and anchor.party else "empty_ref" if anchor.reference else "empty_party" if anchor.party else "all"
            sources=[index.get((opposite,anchor.account,sign,"ref",anchor.reference),()),
                     index.get((opposite,anchor.account,sign,"party",anchor.party),()),
                     index.get((opposite,anchor.account,sign,"weak",anchor.day,anchor.amount_minor,mode),())]
            for source in sources:
                for other in source:
                    if abs((anchor.day-other.day).days)>settings.window_days or abs(other.amount_minor)>abs(anchor.amount_minor):continue
                    basis,conflicts=relation_basis(records,(anchor.id,),(other.id,))
                    weak=(anchor.day==other.day and anchor.amount_minor==other.amount_minor
                          and not(anchor.reference and other.reference and anchor.reference!=other.reference)
                          and not(anchor.party and other.party and anchor.party!=other.party))
                    if basis!="人工指定" or weak:possible[other.id]=other
            cached[key]=tuple(sorted(possible.values(),key=lambda r:r.id))
        pool=cached[key]
        if len(pool)>settings.max_pool:
            head=range_heads.get(key)
            if head:graph.limited((head,anchor.id),"可组成记录池超过 16 条，未穷尽匹配")
            else:
                graph.limited((anchor.id,)+tuple(r.id for r in pool),"可组成记录池超过 16 条，未穷尽匹配")
                range_heads[key]=anchor.id
            continue
        anchor_count=0
        for k in range(1,min(settings.max_parts,len(pool))+1):
            for parts in combinations(pool,k):
                if count>=settings.project_budget:
                    graph.limited(tuple(r.id for r in sides["bank"]+sides["ledger"]),"项目搜索预算已达到上限，未搜索完成")
                    return graph.finish()
                if anchor_count>=settings.anchor_budget:
                    graph.limited((anchor.id,)+tuple(r.id for r in pool),"单笔搜索预算已达到上限")
                    break
                count+=1;anchor_count+=1
                if count%250==0:check_cancel(cancelled)
                if sum(r.amount_minor for r in parts)!=anchor.amount_minor:continue
                if k>1 and not anchor.amount_minor:continue
                rows=(anchor,)+parts
                if (max(r.day for r in rows)-min(r.day for r in rows)).days>settings.window_days:continue
                left=(anchor.id,) if anchor.role=="bank" else tuple(r.id for r in parts)
                right=tuple(r.id for r in parts) if anchor.role=="bank" else (anchor.id,)
                left,right=tuple(sorted(left)),tuple(sorted(right))
                basis,conflicts=relation_basis(records,left,right)
                if k>1 and basis=="人工指定":continue
                if basis=="人工指定":basis="同日同额（弱依据）"
                cid=stable_id("business-match-2",*left,"/",*right)
                graph.add(Suggestion(cid,left,right,anchor.amount_minor,basis,conflicts))
    progress("组合对账完成",len(anchors),len(anchors))
    return graph.finish()
