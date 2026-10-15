import json
from dataclasses import replace
from pathlib import Path
import pytest
from test_review import project,event
from local_reconcile.review import apply_review
from local_reconcile.project_store import save_project,load_project
from local_reconcile.domain import LocalReconcileError

def test_roundtrip_after_source_removed(tmp_path):
    s=project()
    s=apply_review(s,event(s,"confirm",note="已核实"))
    p=tmp_path/"中文 项目.lrproj"
    save_project(s,p)
    assert load_project(p)==s
    assert load_project(p).bank.raw.rows[0].cells[3].value=="A"

def test_atomic_failure_keeps_old(tmp_path,monkeypatch):
    from local_reconcile import project_store
    p=tmp_path/"project.lrproj";save_project(project(),p);before=p.read_bytes()
    def fail(*args):
        raise PermissionError("locked")
    monkeypatch.setattr(project_store.os,"replace",fail)
    with pytest.raises(LocalReconcileError):
        save_project(project(),p)
    assert p.read_bytes()==before
    assert list(tmp_path.glob("*.tmp"))==[]

def test_tampered_references(tmp_path):
    s=project();s=apply_review(s,event(s,"confirm"))
    p=tmp_path/"bad.lrproj";save_project(s,p)
    text=p.read_text(encoding="utf-8")
    p.write_text(text.replace('"bank-0"','"unknown-row"',1),encoding="utf-8")
    with pytest.raises(LocalReconcileError):
        load_project(p)

def test_future_schema(tmp_path):
    p=tmp_path/"future.lrproj";save_project(project(),p)
    content=json.loads(p.read_text(encoding="utf-8"));content["schema_version"]=99
    p.write_text(json.dumps(content),encoding="utf-8")
    with pytest.raises(LocalReconcileError):
        load_project(p)

def test_source_fingerprint(tmp_path):
    s=project();p=tmp_path/"a.lrproj";save_project(s,p)
    restored=load_project(p)
    assert restored.bank.raw.sha256==s.bank.raw.sha256
    assert restored.review==s.review

def test_oversized_save_keeps_previous(tmp_path,monkeypatch):
    from local_reconcile import project_store
    p=tmp_path/"a.lrproj";save_project(project(),p);before=p.read_bytes()
    monkeypatch.setattr(project_store,"MAX_PROJECT_BYTES",10)
    with pytest.raises(LocalReconcileError):
        save_project(project(),p)
    assert p.read_bytes()==before
