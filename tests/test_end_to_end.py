import hashlib
from pathlib import Path
from local_reconcile.importers import read_table
from local_reconcile.normalize import normalize
from local_reconcile.matching import reconcile
from local_reconcile.review import confirm_batch,classify_rows
from local_reconcile.project_store import save_project,load_project
from local_reconcile.export_xlsx import export_report
from local_reconcile.domain import MappingSpec,MatchConfig,ProjectSnapshot

def demo_project():
    root=Path(__file__).resolve().parents[1]/"src"/"local_reconcile"/"resources"
    m=MappingSpec(party_col=2,reference_col=3,summary_col=4,declared_account="SYNTHETIC-001",confirmed=True)
    bank=normalize(read_table(root/"demo_bank.csv","bank"),m)
    ledger=normalize(read_table(root/"demo_ledger.csv","ledger"),m)
    return ProjectSnapshot(1,bank,ledger,MatchConfig(),reconcile(bank,ledger,MatchConfig()))

def test_source_unchanged_end_to_end(tmp_path):
    root=Path(__file__).resolve().parents[1]/"src"/"local_reconcile"/"resources"
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.csv")}
    s=demo_project()
    assert len(s.result.candidates)==8
    assert len(s.result.groups)==1
    assert len(s.result.differences)==1 and s.result.differences[0].delta_minor==1000
    assert sum(t.amount_minor for t in s.bank.transactions)==1153150
    strong=tuple(c.id for c in s.result.candidates if c.rule=="reference")
    s=confirm_batch(s,strong)
    assert len(s.review.pairs)==4
    states=classify_rows(s)
    assert sum(states[t.id]=="pending" for t in s.bank.transactions)==2
    assert sum(states[t.id]=="unmatched" for t in s.bank.transactions)==2
    p=tmp_path/"project.lrproj";save_project(s,p)
    restored=load_project(p)
    export_report(restored,tmp_path/"report.xlsx")
    assert restored==s
    assert {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.csv")}==before

def test_deterministic_reopen(tmp_path):
    s=demo_project();p=tmp_path/"project.lrproj";save_project(s,p)
    assert load_project(p).result==demo_project().result
