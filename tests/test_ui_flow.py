import time
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
import pytest
from local_reconcile.app import create_application
from local_reconcile.ui.main_window import MainWindow
from local_reconcile.project_store import load_project

@pytest.fixture(scope="session")
def app():
    return create_application([])

def wait_until(app,predicate,seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        QTest.qWait(10)
    assert predicate(),"UI operation did not finish"

def test_demo_import_review_save_export(app,tmp_path):
    w=MainWindow();w.show()
    QTest.mouseClick(w.demo_button,Qt.LeftButton)
    wait_until(app,lambda:w.import_page.bank.table is not None)
    assert not w.import_page.confirm_box.isChecked()
    assert w.snapshot is None
    w.import_page.confirm_box.setChecked(True)
    QTest.mouseClick(w.import_page.run_button,Qt.LeftButton)
    wait_until(app,lambda:w.snapshot is not None)
    assert len(w.snapshot.result.candidates)>=3
    w.results_page.table.selectRow(0)
    QTest.mouseClick(w.results_page.confirm_button,Qt.LeftButton)
    assert len(w.snapshot.review.pairs)==1
    p=tmp_path/"示例 项目.lrproj"
    w.save_to(p)
    assert not w.dirty and load_project(p)==w.snapshot
    r=tmp_path/"报告.xlsx";w.export_to(r)
    wait_until(app,lambda:r.exists())
    w.open_from(p)
    wait_until(app,lambda:w.snapshot is not None and not w.busy)
    assert len(w.snapshot.review.pairs)==1
    w.dirty=False;w.close()

def test_config_change_requires_new_run(app):
    w=MainWindow();w.load_demo()
    wait_until(app,lambda:w.import_page.bank.table is not None)
    w.import_page.confirm_box.setChecked(True);w.run_reconciliation()
    wait_until(app,lambda:w.snapshot is not None)
    before=w.snapshot
    assert not w.begin_new_run(allow_discard=False)
    assert w.snapshot is before
    assert w.begin_new_run(allow_discard=True)
    assert w.snapshot is None
    w.dirty=False;w.close()

def test_close_with_unsaved_changes(app):
    w=MainWindow();w.dirty=True
    assert not w.can_close("cancel")
    assert w.can_close("discard")
    assert not w.can_close("save")  # no save destination supplied
    w.dirty=False;w.close()
