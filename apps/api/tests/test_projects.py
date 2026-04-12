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
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Session:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    import api.main as api_main

    api_main.storage = LocalFilesystemStorage(str(tmp_path / "artifacts"))
    api_main.SNAPSHOT_BASE = str(tmp_path / "snapshots")
    return TestClient(app)


def test_project_crud(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    create_response = client.post(
        "/projects",
        json={
            "owner_email": "test@example.com",
            "owner_display_name": "Test User",
            "name": "motor-driver",
            "description": "DC motor board",
        },
    )
    assert create_response.status_code == 200
    project = create_response.json()

    list_response = client.get("/projects")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = client.get(f"/projects/{project['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "motor-driver"


def test_snapshot_creation(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)

    project = client.post(
        "/projects",
        json={
            "owner_email": "builder@example.com",
            "name": "buck-converter",
            "description": "Power stage",
        },
    ).json()

    snapshot_response = client.post(
        f"/projects/{project['id']}/snapshots",
        json={
            "title": "Initial layout",
            "notes": "Accepted patch #1",
            "files": [
                {"path": "README.md", "content": "# Buck converter\n"},
                {"path": "design/netlist.kicad", "content": "(netlist v1)"},
            ],
        },
    )
    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["git_commit_hash"]

    snapshots_response = client.get(f"/projects/{project['id']}/snapshots")
    assert snapshots_response.status_code == 200
    assert len(snapshots_response.json()) == 1
    assert snapshots_response.json()[0]["artifact_dir"].endswith("initial_layout")


def test_verification_runs(tmp_path: Path, monkeypatch) -> None:
    client = build_test_client(tmp_path)
    project = client.post(
        "/projects",
        json={"owner_email": "verify@example.com", "name": "verify-board", "description": "verify"},
    ).json()

    monkeypatch.setattr(
        "api.main.run_kicad_erc",
        lambda _path: {
            "tool": "kicad-erc",
            "status": "completed",
            "issues": [{"id": "ERC_PWR", "severity": "warning", "message": "power input not driven U1 Net-/3V3"}],
        },
    )

    create_run_response = client.post(f"/projects/{project['id']}/verification-runs")
    assert create_run_response.status_code == 200
    run_payload = create_run_response.json()
    assert run_payload["normalized_output"]["tool"] == "kicad-erc"
    assert run_payload["status"] == "completed"

    list_response = client.get(f"/projects/{project['id']}/verification-runs")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    detail_response = client.get(f"/projects/{project['id']}/verification-runs/{run_payload['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["normalized_output"]["findings"][0]["code"] == "ERC_PWR"
