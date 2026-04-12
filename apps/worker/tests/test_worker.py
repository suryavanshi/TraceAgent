from worker.main import run, run_erc_verification_job


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
