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

