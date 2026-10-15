"""Capture the actual application, using synthetic data only."""
import argparse,json,time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from local_reconcile.app import create_application
from local_reconcile.ui.main_window import MainWindow

def capture(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    app=create_application([]);w=MainWindow();w.show();app.processEvents()
    def image(name):
        app.processEvents();QTest.qWait(100)
        if not w.grab().save(str(output/name)):raise RuntimeError("capture failed")
    image("01-home.png")
    w.load_demo()
    deadline=time.monotonic()+15
    while w.busy and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    if w.busy:raise RuntimeError("demo import timed out")
    image("02-import.png")
    w.import_page.confirm_box.setChecked(True);w.run_reconciliation()
    deadline=time.monotonic()+15
    while w.busy and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    if w.snapshot is None:raise RuntimeError("demo reconciliation failed")
    candidates={c.id:c for c in w.snapshot.result.candidates}
    first_strong=next(i for i,cid in enumerate(w.results_page.candidate_ids) if candidates[cid].rule=="reference")
    w.results_page.table.selectRow(first_strong);image("03-results.png")
    w.review_selection("confirm");image("04-confirmed.png")
    w.save_to(output/"synthetic-demo.lrproj")
    w.export_to(output/"synthetic-report.xlsx")
    while w.busy and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    if w.busy:raise RuntimeError("demo export timed out")
    image("05-exported.png");w.dirty=False;w.close()
    return {"capture":"actual application", "data":"synthetic", "frames":5}

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output-dir",type=Path,required=True);a=p.parse_args()
    result=capture(a.output_dir)
    (a.output_dir/"capture.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
