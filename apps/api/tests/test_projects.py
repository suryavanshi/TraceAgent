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
    api_main.STORAGE_BASE = str(tmp_path / "artifacts")
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
    monkeypatch.setattr(
        "api.main.run_kicad_drc",
        lambda _path: {
            "tool": "kicad-drc",
            "status": "completed",
            "issues": [{"id": "DRC_CRDY", "severity": "error", "message": "courtyard overlap U1 U2"}],
        },
    )
    monkeypatch.setattr(
        "api.main.run_manufacturability_checks",
        lambda _path, current_target_amps=1.0: {
            "tool": "manufacturability-heuristics",
            "status": "completed",
            "issues": [{"id": "MFG_TRACE_WIDTH", "severity": "warning", "message": "trace width below target"}],
        },
    )

    create_run_response = client.post(f"/projects/{project['id']}/verification-runs")
    assert create_run_response.status_code == 200
    run_payload = create_run_response.json()
    assert run_payload["normalized_output"]["tool"] == "verification-suite"
    assert run_payload["status"] == "completed"
    assert run_payload["normalized_output"]["checks"]["erc"]["finding_count"] == 1
    assert run_payload["normalized_output"]["checks"]["drc"]["finding_count"] == 1
    assert run_payload["normalized_output"]["checks"]["manufacturability"]["finding_count"] == 1

    list_response = client.get(f"/projects/{project['id']}/verification-runs")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    detail_response = client.get(f"/projects/{project['id']}/verification-runs/{run_payload['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["normalized_output"]["findings"][0]["code"] == "ERC_PWR"


def test_release_bundle_creation_and_listing(tmp_path: Path, monkeypatch) -> None:
    client = build_test_client(tmp_path)
    project = client.post(
        "/projects",
        json={"owner_email": "release@example.com", "name": "release-board", "description": "release"},
    ).json()

    snapshot = client.post(
        f"/projects/{project['id']}/snapshots",
        json={
            "title": "Release Snapshot",
            "files": [{"path": "README.md", "content": "release snapshot"}],
        },
    ).json()

    generated_root = tmp_path / "artifacts" / project["artifact_root_dir"] / "generated"
    (generated_root / "schematic_ir").mkdir(parents=True, exist_ok=True)
    (generated_root / "board_ir").mkdir(parents=True, exist_ok=True)
    (generated_root / "schematic_ir" / "schematic_ir.json").write_text(
        """
{
  "symbols": [{"symbol_id": "sym_u", "kind": "mcu"}],
  "component_instances": [{"instance_id": "u1", "symbol_id": "sym_u", "reference": "U1", "properties": {"value": "MCU", "package": "QFN32"}}],
  "nets": [{"net_id": "n1", "name": "GND", "nodes": []}]
}
""".strip(),
        encoding="utf-8",
    )
    (generated_root / "board_ir" / "board_ir.json").write_text(
        """
{
  "board_outline": {"shape": "rectangle", "dimensions_mm": {"width": 50, "height": 40}},
  "stackup": [{"name": "F.Cu", "kind": "copper", "thickness_um": 35}],
  "footprints": [{"footprint_id": "fp_u1", "instance_id": "u1", "library_ref": "Package_QFN:QFN-32", "package": "QFN32"}],
  "mounting_holes": [],
  "fixed_edge_connectors": [],
  "placement_constraints": [],
  "design_rules": [],
  "net_classes": [],
  "keepouts": [],
  "zones": [],
  "routing_intents": []
}
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr("worker.release.run_kicad_erc", lambda _path: {"tool": "kicad-erc", "status": "completed", "issues": []})
    monkeypatch.setattr("worker.release.run_kicad_drc", lambda _path: {"tool": "kicad-drc", "status": "completed", "issues": []})
    monkeypatch.setattr(
        "api.main.build_release_bundle",
        lambda **_kwargs: type(
            "BundleResult",
            (),
            {
                "output_dir": generated_root / "releases" / "release-board_v1.0.0_abcd1234",
                "manifest": {
                    "snapshot": {"snapshot_id": snapshot["id"], "git_commit_hash": snapshot["git_commit_hash"]},
                    "contents": [{"path": "bom/bom.csv", "sha256": "deadbeef"}],
                },
                "files": {"manifest": str(generated_root / "releases" / "manifest.json"), "bom": "bom/bom.csv"},
            },
        )(),
    )

    create_release = client.post(
        f"/projects/{project['id']}/releases",
        json={"snapshot_id": snapshot["id"], "version": "v1.0.0", "notes": "first release"},
    )
    assert create_release.status_code == 200
    payload = create_release.json()
    assert payload["manifest"]["snapshot"]["snapshot_id"] == snapshot["id"]
    assert payload["manifest"]["snapshot"]["git_commit_hash"] == snapshot["git_commit_hash"]
    assert any(item["path"] == "bom/bom.csv" for item in payload["manifest"]["contents"])

    list_releases = client.get(f"/projects/{project['id']}/releases")
    assert list_releases.status_code == 200
    assert len(list_releases.json()) == 1


def test_seed_projects_endpoint(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    response = client.get("/seed-projects")
    assert response.status_code == 200
    payload = response.json()
    assert any(item["slug"] == "esp32_sensor_board" for item in payload)
