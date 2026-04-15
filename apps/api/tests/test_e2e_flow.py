from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.db import Base, get_db
from api.main import app
from api.storage import LocalFilesystemStorage


def build_test_client(tmp_path: Path) -> TestClient:
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Session:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    import api.main as api_main

    api_main.storage = LocalFilesystemStorage(str(tmp_path / "artifacts"))
    api_main.STORAGE_BASE = str(tmp_path / "artifacts")
    api_main.SNAPSHOT_BASE = str(tmp_path / "snapshots")
    return TestClient(app)


def test_full_pipeline_e2e(tmp_path: Path, monkeypatch) -> None:
    client = build_test_client(tmp_path)

    monkeypatch.setattr(
        "api.main.compile_and_export_project",
        lambda **kwargs: {
            "project": str(tmp_path / "compiled" / "demo.kicad_pro"),
            "schematic": str(tmp_path / "compiled" / "demo.kicad_sch"),
            "sym_lib_table": str(tmp_path / "compiled" / "sym-lib-table"),
            "svg": str(tmp_path / "compiled" / "demo.svg"),
            "pdf": str(tmp_path / "compiled" / "demo.pdf"),
        },
    )
    monkeypatch.setattr(
        "api.main.compile_board_project",
        lambda **kwargs: {"pcb": str(tmp_path / "compiled" / "demo.kicad_pcb")},
    )
    compiled = tmp_path / "compiled"
    compiled.mkdir(parents=True, exist_ok=True)
    (compiled / "demo.kicad_pro").write_text("project", encoding="utf-8")
    (compiled / "demo.kicad_sch").write_text("schematic", encoding="utf-8")
    (compiled / "sym-lib-table").write_text("sym", encoding="utf-8")
    (compiled / "demo.svg").write_text("<svg></svg>", encoding="utf-8")
    (compiled / "demo.pdf").write_bytes(b"pdf")
    (compiled / "demo.kicad_pcb").write_text("pcb", encoding="utf-8")

    monkeypatch.setattr("api.main.run_kicad_erc", lambda _path: {"tool": "erc", "status": "completed", "issues": []})
    monkeypatch.setattr("api.main.run_kicad_drc", lambda _path: {"tool": "drc", "status": "completed", "issues": []})
    monkeypatch.setattr(
        "api.main.run_manufacturability_checks",
        lambda _path, current_target_amps=1.0: {"tool": "mfg", "status": "completed", "issues": []},
    )

    project = client.post(
        "/projects",
        json={"owner_email": "e2e@example.com", "name": "pipeline-board", "description": "e2e"},
    ).json()

    derive = client.post(
        f"/projects/{project['id']}/requirements/derive",
        json={"latest_user_request": "Build a robust sensor board", "chat_history": [{"role": "user", "content": "Need board"}]},
    )
    assert derive.status_code == 200

    synth = client.post(
        f"/projects/{project['id']}/schematic/synthesize",
        json={"circuit_spec": derive.json()["proposed_circuit_spec"], "selected_parts": []},
    )
    assert synth.status_code == 200

    verify = client.post(f"/projects/{project['id']}/verification-runs")
    assert verify.status_code == 200
    assert verify.json()["normalized_output"]["tool"] == "verification-suite"

    patch = client.post(
        f"/projects/{project['id']}/visual-edits/sync",
        json={
            "board_ir": synth.json()["board_ir"],
            "edits": [],
        },
    )
    assert patch.status_code == 200

    snapshot = client.post(
        f"/projects/{project['id']}/snapshots",
        json={"title": "post-patch", "files": [{"path": "README.md", "content": "e2e"}]},
    )
    assert snapshot.status_code == 200

    monkeypatch.setattr(
        "api.main.build_release_bundle",
        lambda **_kwargs: type(
            "BundleResult",
            (),
            {
                "output_dir": tmp_path / "release",
                "manifest": {"snapshot": {"snapshot_id": snapshot.json()["id"]}, "contents": [{"path": "bom/bom.csv"}]},
                "files": {"manifest": str(tmp_path / "release" / "manifest.json")},
            },
        )(),
    )

    release = client.post(
        f"/projects/{project['id']}/releases",
        json={"snapshot_id": snapshot.json()["id"], "version": "v1.0.0", "notes": "e2e"},
    )
    assert release.status_code == 200
