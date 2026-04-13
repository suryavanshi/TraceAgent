from worker.main import run, run_erc_verification_job, run_pcb_verification_job


def test_worker_entrypoint_exists() -> None:
    assert callable(run)


def test_erc_job_normalizes(monkeypatch) -> None:
    monkeypatch.setattr(
        "worker.main.run_kicad_erc",
        lambda _path: {"tool": "kicad-erc", "status": "completed", "issues": [{"id": "ERC_1", "severity": "error", "message": "multiple drivers U1 U2"}]},
    )
    result = run_erc_verification_job("/tmp/project.kicad_pro")
    assert result["status"] == "completed"
    assert result["normalized_output"]["findings"]


def test_pcb_verification_job_runs_all_pipelines(monkeypatch) -> None:
    monkeypatch.setattr("worker.main.run_kicad_erc", lambda _path: {"tool": "kicad-erc", "status": "completed", "issues": []})
    monkeypatch.setattr("worker.main.run_kicad_drc", lambda _path: {"tool": "kicad-drc", "status": "completed", "issues": [{"id": "DRC_1", "severity": "warning", "message": "courtyard overlap U1 U2"}]})
    monkeypatch.setattr(
        "worker.main.run_manufacturability_checks",
        lambda _path, current_target_amps=1.0: {"tool": "manufacturability-heuristics", "status": "completed", "issues": [{"id": "MFG_1", "severity": "warning", "message": "trace width below target"}]},
    )
    result = run_pcb_verification_job("/tmp/project.kicad_pro", "/tmp/board.kicad_pcb")
    assert result["status"] == "completed"
    assert result["normalized_output"]["checks"]["drc"]["finding_count"] == 1
    assert result["normalized_output"]["checks"]["manufacturability"]["finding_count"] == 1
