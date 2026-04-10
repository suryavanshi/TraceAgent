from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.db import Base, get_db
from api.main import app
from api.part_catalog import LocalCuratedPartCatalog
from api.part_resolver import PartConstraint, PartResolver
from design_ir.models import CircuitSpec, NamedObject


def build_test_client(tmp_path: Path) -> TestClient:
    db_url = f"sqlite:///{tmp_path / 'test_parts.db'}"
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
    return TestClient(app)


def _spec_for_block(block_name: str, preferred_parts: list[str] | None = None, banned_parts: list[str] | None = None) -> CircuitSpec:
    return CircuitSpec(
        product_name="Part Selection Test",
        summary="part resolver test",
        target_board_type="controller",
        functional_blocks=[NamedObject(name=block_name)],
        preferred_parts=preferred_parts or [],
        banned_parts=banned_parts or [],
    )


def test_regulator_selection() -> None:
    resolver = PartResolver(LocalCuratedPartCatalog())
    spec = _spec_for_block("Primary regulator")
    result = resolver.review(spec, constraints={"regulator": PartConstraint(min_voltage_v=5.0, min_current_a=0.5, package="SOT-223")})

    assert result.block_reviews[0].candidates
    winner = result.block_reviews[0].candidates[0]
    assert winner.part.mpn == "AMS1117-3.3"
    assert winner.confidence > 0
    assert winner.rationale


def test_mcu_selection() -> None:
    resolver = PartResolver(LocalCuratedPartCatalog())
    spec = _spec_for_block("Main MCU")
    result = resolver.review(spec, constraints={"mcu": PartConstraint(max_voltage_v=3.3, package="LQFP-48")})

    assert result.block_reviews[0].candidates
    assert result.block_reviews[0].candidates[0].part.mpn == "STM32F411CEU6"


def test_connector_selection() -> None:
    resolver = PartResolver(LocalCuratedPartCatalog())
    spec = _spec_for_block("USB connector")
    result = resolver.review(spec, constraints={"connector": PartConstraint(interface="USB2.0", min_current_a=1.5)})

    assert result.block_reviews[0].candidates
    winner = result.block_reviews[0].candidates[0]
    assert winner.part.mpn == "TYPE-C-31-M-12"
    assert winner.part.symbol_ref.identifier == "USB_C_Receptacle_USB2.0"


def test_esd_protection_part_selection() -> None:
    resolver = PartResolver(LocalCuratedPartCatalog())
    spec = _spec_for_block("USB ESD protection")
    result = resolver.review(spec, constraints={"esd": PartConstraint(interface="USB2.0", max_voltage_v=5.0)})

    assert result.block_reviews[0].candidates
    assert result.block_reviews[0].candidates[0].part.mpn == "USBLC6-2SC6"


def test_review_endpoint_honors_preferred_and_banned_parts(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    project = client.post(
        "/projects",
        json={
            "owner_email": "parts@example.com",
            "name": "parts-review",
        },
    ).json()

    response = client.post(
        f"/projects/{project['id']}/parts/review",
        json={
            "circuit_spec": {
                "schema_version": "1.0.0",
                "product_name": "Review target",
                "summary": "Select parts",
                "target_board_type": "controller",
                "functional_blocks": [{"name": "Primary regulator"}],
                "interfaces": [],
                "power_rails": [],
                "environmental_constraints": [],
                "mechanical_constraints": [],
                "cost_constraints": [],
                "manufacturing_constraints": [],
                "preferred_parts": ["AMS1117-3.3"],
                "banned_parts": [],
                "open_questions": []
            },
            "constraints_by_role": {
                "regulator": {
                    "min_voltage_v": 5.0,
                    "min_current_a": 0.5,
                    "package": "SOT-223"
                }
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    candidates = payload["block_reviews"][0]["candidates"]
    assert candidates
    assert candidates[0]["mpn"] == "AMS1117-3.3"
    assert candidates[0]["confidence"] > 0.7
    assert candidates[0]["rationale"]

    banned_response = client.post(
        f"/projects/{project['id']}/parts/review",
        json={
            "circuit_spec": {
                "schema_version": "1.0.0",
                "product_name": "Review target",
                "summary": "Select parts",
                "target_board_type": "controller",
                "functional_blocks": [{"name": "Primary regulator"}],
                "interfaces": [],
                "power_rails": [],
                "environmental_constraints": [],
                "mechanical_constraints": [],
                "cost_constraints": [],
                "manufacturing_constraints": [],
                "preferred_parts": [],
                "banned_parts": ["AMS1117-3.3"],
                "open_questions": []
            },
            "constraints_by_role": {
                "regulator": {
                    "min_voltage_v": 5.0,
                    "min_current_a": 0.5,
                    "package": "SOT-223"
                }
            }
        },
    )
    assert banned_response.status_code == 200
    assert banned_response.json()["block_reviews"][0]["candidates"] == []
