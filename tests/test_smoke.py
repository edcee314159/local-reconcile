from local_reconcile.smoke import run_smoke

def test_smoke_outputs_independent_demo_artifacts(tmp_path):
    result=run_smoke(tmp_path)
    assert result["status"]=="ok"
    assert result["confirmed_pairs"]==4
    assert result["candidate_count"]==8
    assert (tmp_path/"synthetic-project.lrproj").is_file()
    assert (tmp_path/"synthetic-report.xlsx").is_file()
