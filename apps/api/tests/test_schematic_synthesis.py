from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.db import Base, get_db
from api.main import app
from api.schematic_synthesis import (
    DeterministicRuleEngine,
    RuleBasedSchematicPlanner,
    SchematicLintEngine,
    SchematicSynthesisAgent,
    SelectedPart,
)
from design_ir.models import CircuitSpec, NamedObject


def build_test_client(tmp_path: Path) -> TestClient:
    db_url = f"sqlite:///{tmp_path / 'test_schematic_synthesis.db'}"
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


def _sample_spec() -> CircuitSpec:
    return CircuitSpec(
        product_name="Synth target",
        summary="Schematic synthesis test",
        target_board_type="sensor-node",
        functional_blocks=[NamedObject(name="Main MCU"), NamedObject(name="USB connector")],
        interfaces=[NamedObject(name="I2C")],
        power_rails=[NamedObject(name="VBUS"), NamedObject(name="3V3")],
    )


def test_schematic_synthesis_agent_separates_planning_and_rules() -> None:
    planner = RuleBasedSchematicPlanner()
    rule_engine = DeterministicRuleEngine()
    agent = SchematicSynthesisAgent(planner=planner, rule_engine=rule_engine)

    result = agent.synthesize(
        circuit_spec=_sample_spec(),
        selected_parts=[
            SelectedPart(functional_role="mcu", mpn="STM32F411CEU6", symbol_id="sym_mcu", reference_prefix="U"),
            SelectedPart(functional_role="usb-connector", mpn="TYPE-C-31-M-12", symbol_id="sym_usb", reference_prefix="J"),
        ],
    )

    assert result.schematic_ir.component_instances
    assert result.power_tree
    assert result.support_passives
    assert result.decoupling_recommendations
    assert any(entry.provenance == "llm" for entry in result.provenance)
    assert any(entry.provenance == "rules" for entry in result.provenance)


def test_lint_flags_broken_power_tree() -> None:
    planner = RuleBasedSchematicPlanner()
    plan = planner.plan(
        _sample_spec(), [SelectedPart(functional_role="mcu", mpn="STM32F411CEU6", symbol_id="sym_mcu")]
    )
    if plan.power_tree:
        plan.power_tree[0].sink_net = "NON_EXISTENT"

    result = DeterministicRuleEngine().enrich(plan)
    warnings = SchematicLintEngine().lint(result)

    assert any(warning.code == "BROKEN_POWER_TREE" for warning in warnings)


def test_schematic_synthesis_endpoint_persists_ir(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    project = client.post(
        "/projects",
        json={
            "owner_email": "schematic@example.com",
            "name": "schematic-synthesis",
        },
    ).json()

    response = client.post(
        f"/projects/{project['id']}/schematic/synthesize",
        json={
            "circuit_spec": _sample_spec().model_dump(),
            "selected_parts": [
                {"functional_role": "mcu", "mpn": "STM32F411CEU6", "symbol_id": "sym_mcu", "reference_prefix": "U"},
                {
                    "functional_role": "usb-connector",
                    "mpn": "TYPE-C-31-M-12",
                    "symbol_id": "sym_usb",
                    "reference_prefix": "J",
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schematic_ir"]["component_instances"]
    assert payload["board_ir"]["footprints"]
    assert "warnings" in payload
    assert Path(payload["saved_path"]).exists()
    assert Path(payload["board_ir_path"]).exists()
    assert payload["board_metadata"]["routing_state"]["routed_count"] == 0
    assert "routing_plan_summary" in payload["board_metadata"]


@pytest.mark.parametrize(
    "fixture_name",
    ["example_design_sensor_node.json", "example_design_gateway.json"],
)
def test_schematic_synthesis_endpoint_compiles_kicad_artifacts_from_examples(tmp_path: Path, fixture_name: str) -> None:
    fixture_path = Path(__file__).resolve().parents[3] / "packages" / "design-ir" / "tests" / "fixtures" / fixture_name
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    client = build_test_client(tmp_path)
    project = client.post(
        "/projects",
        json={
            "owner_email": "schematic@example.com",
            "name": f"schematic-{fixture_name}",
        },
    ).json()

    response = client.post(
        f"/projects/{project['id']}/schematic/synthesize",
        json={
            "circuit_spec": payload["circuit_spec"],
            "selected_parts": [],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert Path(result["kicad_project_path"]).exists()
    assert Path(result["kicad_schematic_path"]).exists()
    assert Path(result["kicad_sym_lib_table_path"]).exists()
    assert Path(result["kicad_pcb_path"]).exists()
    assert Path(result["schematic_svg_path"]).exists()
    assert Path(result["schematic_pdf_path"]).exists()
    assert "<svg" in result["schematic_svg"]
