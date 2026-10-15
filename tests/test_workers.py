import time
import pytest
from PySide6.QtTest import QTest
from local_reconcile.app import create_application
from local_reconcile.ui.workers import JobRunner

def wait(app,predicate):
    deadline=time.monotonic()+5
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();QTest.qWait(10)
    assert predicate()

def test_stale_job_ignored():
    app=create_application([]);runner=JobRunner();results=[]
    runner.submit(1,lambda progress,cancelled:(time.sleep(.05),"old")[1],results.append,lambda e:results.append("error"))
    runner.submit(2,lambda progress,cancelled:"new",results.append,lambda e:results.append("error"))
    wait(app,lambda:results==["new"])
    QTest.qWait(100);app.processEvents()
    assert results==["new"]
    runner.shutdown()

def test_cancel_keeps_valid_snapshot():
    app=create_application([]);runner=JobRunner();results=[]
    runner.submit(1,lambda progress,cancelled:(time.sleep(.05),"discard")[1],results.append,lambda e:results.append("error"))
    runner.cancel(1)
    QTest.qWait(150);app.processEvents()
    assert results==[]
    runner.shutdown()
