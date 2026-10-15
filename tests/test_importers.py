from concurrent.futures import CancelledError
from pathlib import Path
import hashlib, io, zipfile
import pytest
from openpyxl import Workbook
from local_reconcile.importers import read_table, inspect_file
from local_reconcile.domain import LocalReconcileError

def test_csv_multiline_source_line(tmp_path):
    p=tmp_path/"中文 流水.csv"
    p.write_text('日期,金额,摘要\n2026-10-15,10,"第一行\n第二行"\n2026-10-16,20,其他\n',encoding="utf-8-sig",newline="\n")
    before=p.read_bytes()
    t=read_table(p,"bank")
    assert len(t.rows)==2
    assert [r.source_line for r in t.rows]==[2,4]
    assert t.rows[0].cells[2].value=="第一行\n第二行"
    assert t.sha256==hashlib.sha256(before).hexdigest()
    assert p.read_bytes()==before

def test_duplicate_headers_use_index(tmp_path):
    p=tmp_path/"dup.csv"; p.write_text("日期,金额,金额\n2026-10-15,1,2",encoding="utf-8")
    t=read_table(p,"bank")
    assert t.headers==("日期","金额","金额")
    assert t.rows[0].cells[2].value=="2"

def test_formula_missing_cache(tmp_path):
    p=tmp_path/"公式.xlsx"
    w=Workbook(); s=w.active; s.title="流水"
    s.append(["日期","金额"]); s.append(["2026-10-15","=1+1"]); w.save(p); w.close()
    assert inspect_file(p,"bank")==("流水",)
    t=read_table(p,"bank","流水")
    assert t.rows[0].cells[1].kind=="formula"
    assert t.rows[0].cells[1].cached_value is None
    assert t.excel_epoch.isoformat()=="1899-12-30"

def test_oversized_dimensions(tmp_path):
    p=tmp_path/"维度.xlsx"
    w=Workbook(); w.active.append(["日期","金额"]); w.active.append(["2026-10-15",10]); w.save(p); w.close()
    output=io.BytesIO()
    with zipfile.ZipFile(p) as z, zipfile.ZipFile(output,"w") as out:
        for n in z.namelist():
            data=z.read(n)
            if n=="xl/worksheets/sheet1.xml":
                data=data.replace(b'A1:B2',b'A1:XFD1048576')
            out.writestr(n,data)
    p.write_bytes(output.getvalue())
    t=read_table(p,"bank")
    assert len(t.rows)==1
    assert len(t.headers)==2

def test_cancel_import(tmp_path):
    p=tmp_path/"cancel.csv"; p.write_text("日期,金额\n2026-01-01,1",encoding="utf-8")
    with pytest.raises(CancelledError):
        read_table(p,"bank",cancelled=lambda:True)

@pytest.mark.parametrize("name,content",[("broken.xlsx",b"bad"),("bad.csv",b"\xff"),("empty.csv",b""),("old.xls",b"bad")])
def test_invalid_files(tmp_path,name,content):
    p=tmp_path/name; p.write_bytes(content)
    with pytest.raises(LocalReconcileError):
        read_table(p,"bank")

def test_header_row_and_source_unchanged(tmp_path):
    p=tmp_path/"前言.csv"; p.write_text("虚构数据\n日期,金额\n2026-01-01,10",encoding="utf-8")
    t=read_table(p,"bank",header_row=2)
    assert t.rows[0].source_line==3
    assert t.header_row==2

def test_file_limit(tmp_path):
    p=tmp_path/"large.csv"
    with p.open("wb") as f:
        f.truncate(26*1024*1024)
    with pytest.raises(LocalReconcileError):
        read_table(p,"bank")

