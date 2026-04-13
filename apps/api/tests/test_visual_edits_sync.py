from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.db import Base, get_db
from api.main import app


def build_test_client(tmp_path: Path) -> TestClient:
    db_url = f"sqlite:///{tmp_path / 'test_visual_edits.db'}"
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
    return TestClient(app)


def _board_ir() -> dict:
    return {
        "schema_version": "1.0.0",
        "board_outline": {"shape": "rect", "dimensions_mm": {"width": 20, "height": 20}},
        "stackup": [],
        "footprints": [
            {
                "footprint_id": "fp_u1",
                "instance_id": "u1",
                "package": "QFN-48",
                "placement": {"x_mm": 1.0, "y_mm": 2.0, "rotation_deg": 0},
                "fixed": False,
                "provenance": "rules",
            }
        ],
        "mounting_holes": [],
        "fixed_edge_connectors": [],
        "placement_constraints": [],
        "design_rules": [],
        "net_classes": [],
        "keepouts": [],
        "zones": [],
        "routing_intents": [],
        "placement_decisions": [],
        "placement_visualization": {},
    }


def test_visual_edit_sync_applies_patch_and_summary(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    project = client.post("/projects", json={"owner_email": "visual@example.com", "name": "visual-sync"}).json()

    response = client.post(
        f"/projects/{project['id']}/visual-edits/sync",
        json={
            "board_ir": _board_ir(),
            "edits": [
                {"kind": "move_footprint", "object_id": "footprint:fp_u1", "x_mm": 12.5, "y_mm": 7.25},
                {"kind": "rotate_footprint", "object_id": "footprint:fp_u1", "delta_deg": 90},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["summary"].startswith("Moved footprint:fp_u1")
    assert payload[1]["summary"].startswith("Rotated footprint:fp_u1")
    assert payload[-1]["board_ir"]["footprints"][0]["placement"]["x_mm"] == 12.5
    assert payload[-1]["board_ir"]["footprints"][0]["placement"]["rotation_deg"] == 90
    assert payload[-1]["patch_plan"]["category"] == "rotate_footprint"


def test_visual_edit_undo_reverts_latest_change(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    project = client.post("/projects", json={"owner_email": "visual@example.com", "name": "visual-undo"}).json()

    sync_response = client.post(
        f"/projects/{project['id']}/visual-edits/sync",
        json={
            "board_ir": _board_ir(),
            "edits": [{"kind": "lock_footprint", "object_id": "footprint:fp_u1", "locked": True}],
        },
    )
    assert sync_response.status_code == 200
    assert sync_response.json()[0]["board_ir"]["footprints"][0]["fixed"] is True

    undo_response = client.post(f"/projects/{project['id']}/visual-edits/undo")
    assert undo_response.status_code == 200
    assert undo_response.json()["footprints"][0]["fixed"] is False
