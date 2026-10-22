"""Only run with an explicit built application directory."""
from pathlib import Path
import os,json

def release_dir():
    path=os.environ.get("LOCAL_RECONCILE_RELEASE_DIR")
    assert path,"LOCAL_RECONCILE_RELEASE_DIR must name an actual release folder"
    p=Path(path);assert p.is_dir()
    return p

def test_release_manifest():
    p=release_dir()
    assert (p/"LocalReconcile.exe").is_file()
    assert (p/"LICENSE").is_file()
    assert (p/"THIRD_PARTY_NOTICES.md").is_file()
    assert (p/"third_party"/"sources"/"source-manifest.json").is_file()
    assert len(list((p/"_internal").rglob("Qt6Core.dll")))==1
    assert len(list((p/"_internal").rglob("Qt6Widgets.dll")))==1
    assert len(list((p/"_internal").rglob("python312.dll")))==1

def test_demo_resources_bundled():
    p=release_dir()
    assert list(p.rglob("demo_bank.csv"))
    assert list(p.rglob("demo_ledger.csv"))
    assert list(p.rglob("style.qss"))

def test_no_private_artifacts_in_release():
    p=release_dir()
    assert not list(p.rglob("*.lrproj"))
    assert not list(p.rglob("*.xlsx"))
    assert not list(p.rglob("*.log"))
    assert not list(p.rglob("*.pyc"))

def test_packaged_executable_smoke(tmp_path):
    import subprocess,json
    p=release_dir()
    env=os.environ.copy()
    env["PATH"]=os.environ["SystemRoot"]+r"\System32;"+os.environ["SystemRoot"]
    env.pop("PYTHONPATH",None);env.pop("PYTHONHOME",None)
    env["QT_QPA_PLATFORM"]="offscreen"
    result=subprocess.run([str(p/"LocalReconcile.exe"),"--smoke-test","--output-dir",str(tmp_path/"synthetic-smoke")],
                          env=env,capture_output=True,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0
    data=json.loads((tmp_path/"synthetic-smoke"/"smoke-result.json").read_text(encoding="utf-8"))
    assert data["status"]=="ok" and data["confirmed_pairs"]==4



def test_packaged_five_business_workflows(tmp_path):
    import subprocess
    p=release_dir();env=os.environ.copy()
    env["PATH"]=os.environ["SystemRoot"]+r"\System32;"+os.environ["SystemRoot"]
    env.pop("PYTHONPATH",None);env.pop("PYTHONHOME",None)
    env["QT_QPA_PLATFORM"]="offscreen"
    output=tmp_path/"中文业务 自检"
    result=subprocess.run([str(p/"LocalReconcile.exe"),"--business-smoke-test","--output-dir",str(output)],
                          env=env,capture_output=True,timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0
    data=json.loads((output/"business-smoke.json").read_text(encoding="utf-8"))
    assert data["combination_relations"]==1 and data["difference_explanations"]==1
    assert data["remaining_receivable_minor"]==700000
    assert data["internal_transfers"]==1 and data["closed_periods"]==1

    assert data["many_to_many_relations"]==1 and data["refunds"]==2
    assert data["advance_remaining_minor"]==1000 and data["reopened_receivable_minor"]==3000

    assert data["bank_adjustment_difference_minor"]==0
    assert data["aging_receivable_minor"]==10000 and data["aging_overdue_minor"]==10000
    assert data["historical_adjustment_preserved"] is True
    assert data["credit_receivable_remaining_minor"]==8000 and data["credit_payable_remaining_minor"]==15000
    assert data["duplicate_use_blocked"] is True and data["duplicate_groups_after_exclusion"]==0
    assert data["partner_confirmed_rows"]==1 and data["partner_explained_rows"]==3
    assert data["partner_history_preserved"] is True

    assert data["net_settlement_minor"]==9200 and data["net_settlement_confirmed"]
    assert data["cutoff_missing_minor"]==3000 and data["cutoff_monthly_minor"]==10000
    assert data["cutoff_unmatched_postings"]==1 and data["advanced_history_preserved"]
