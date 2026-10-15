import socket
from test_end_to_end import demo_project
from local_reconcile.project_store import save_project,load_project
from local_reconcile.export_xlsx import export_report

def test_no_network_requests(tmp_path,monkeypatch):
    def fail(*args,**kwargs):raise AssertionError("unexpected network")
    monkeypatch.setattr(socket.socket,"connect",fail)
    monkeypatch.setattr(socket,"create_connection",fail)
    s=demo_project();p=tmp_path/"project.lrproj";save_project(s,p)
    export_report(load_project(p),tmp_path/"report.xlsx")
