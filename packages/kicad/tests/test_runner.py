from trace_kicad.runner import run_kicad_job


def test_run_kicad_job() -> None:
    result = run_kicad_job("erc")
    assert result["status"] == "queued"
