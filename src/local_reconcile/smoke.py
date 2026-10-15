"""Explicit developer self-check, using clearly labelled synthetic data only."""
from pathlib import Path
import json
from .domain import MappingSpec,MatchConfig,ProjectSnapshot
from .importers import read_table
from .normalize import normalize
from .matching import reconcile
from .review import confirm_batch
from .project_store import save_project
from .export_xlsx import export_report

def run_smoke(output_dir):
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    resource=Path(__file__).parent/"resources"
    mapping=MappingSpec(party_col=2,reference_col=3,summary_col=4,declared_account="SYNTHETIC-001",confirmed=True)
    bank=normalize(read_table(resource/"demo_bank.csv","bank"),mapping)
    ledger=normalize(read_table(resource/"demo_ledger.csv","ledger"),mapping)
    result=reconcile(bank,ledger,MatchConfig())
    snapshot=ProjectSnapshot(1,bank,ledger,MatchConfig(),result)
    snapshot=confirm_batch(snapshot,tuple(c.id for c in result.candidates if c.rule=="reference"))
    save_project(snapshot,output/"synthetic-project.lrproj")
    export_report(snapshot,output/"synthetic-report.xlsx")
    status={"status":"ok","data":"synthetic","candidate_count":len(result.candidates),"confirmed_pairs":len(snapshot.review.pairs),"bank_rows":len(bank.transactions),"ledger_rows":len(ledger.transactions)}
    (output/"smoke-result.json").write_text(json.dumps(status,indent=2),encoding="utf-8")
    return status
