"""Reproducible benchmark with synthetic inputs and measured phases."""
import argparse,csv,json,platform,random,time,tracemalloc,importlib.metadata
from pathlib import Path
from local_reconcile.domain import MappingSpec,MatchConfig,ProjectSnapshot
from local_reconcile.importers import read_table
from local_reconcile.normalize import normalize
from local_reconcile.matching import reconcile
from local_reconcile.export_xlsx import export_report

def benchmark(rows,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    records=[[f"2026-10-{i%28+1:02d}",f"{'-' if i%2 else ''}{100+i//100}.{i%100:02d}",f"虚构对方{i%30}",f"SYN-{i:06d}","SYNTHETIC"] for i in range(rows)]
    for role in ("bank","ledger"):
        data=list(records)
        if role=="ledger":random.Random(42).shuffle(data)
        with (output/f"{role}.csv").open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.writer(f);writer.writerow(["日期","金额","对方","共同编号","摘要"]);writer.writerows(data)
    times={};tracemalloc.start();start=time.perf_counter()
    raw=[read_table(output/f"{role}.csv",role) for role in ("bank","ledger")]
    times["read_seconds"]=time.perf_counter()-start
    m=MappingSpec(party_col=2,reference_col=3,summary_col=4,declared_account="SYNTHETIC-001",confirmed=True)
    start=time.perf_counter();b,l=(normalize(t,m) for t in raw);times["normalize_seconds"]=time.perf_counter()-start
    start=time.perf_counter();r=reconcile(b,l,MatchConfig());times["match_seconds"]=time.perf_counter()-start
    start=time.perf_counter();export_report(ProjectSnapshot(1,b,l,MatchConfig(),r),output/"benchmark-report.xlsx");times["export_seconds"]=time.perf_counter()-start
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    result={"data":"synthetic","rows_per_side":rows,"candidate_count":len(r.candidates),"all_expected_candidates":len(r.candidates)==rows,
            "timings":times,"peak_python_memory_mib":peak/1024/1024,"system":platform.platform(),"processor":platform.processor(),
            "python":platform.python_version(),"versions":{n:importlib.metadata.version(n) for n in ("openpyxl","PySide6-Essentials","pyinstaller")}}
    (output/"benchmark.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True,indent=2))
    if len(r.candidates)!=rows:raise RuntimeError("benchmark expected match count differs")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--rows",type=int,default=10000);p.add_argument("--output-dir",type=Path,required=True);a=p.parse_args()
    benchmark(a.rows,a.output_dir)
