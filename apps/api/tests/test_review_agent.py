from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.db import Base, get_db
from api.main import app
from api.review_agent import ReviewAgent
from api.simulation import SimulationService
from design_ir.models import (
    BoardIR,
    BoardOutline,
    CircuitSpec,
    ComponentInstance,
    Constraint,
    Net,
    NetNode,
    NamedObject,
    SchematicIR,
    StackupLayer,
    Symbol,
)


def build_test_client(tmp_path: Path) -> TestClient:
    db_url = f"sqlite:///{tmp_path / 'test_review_agent.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Session:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _sample_schematic() -> SchematicIR:
    _ = CircuitSpec(
        product_name="Review target",
        summary="Review tests",
        target_board_type="sensor-node",
        functional_blocks=[NamedObject(name="Regulator")],
    )
    return SchematicIR(
        symbols=[
            Symbol(symbol_id="sym_reg", kind="regulator"),
            Symbol(symbol_id="sym_r", kind="resistor"),
            Symbol(symbol_id="sym_c", kind="capacitor"),
            Symbol(symbol_id="sym_op", kind="opamp"),
        ],
        component_instances=[
            ComponentInstance(instance_id="u_reg", symbol_id="sym_reg", reference="U1", value="LDO"),
            ComponentInstance(instance_id="r1", symbol_id="sym_r", reference="R1", value="10k"),
            ComponentInstance(instance_id="c1", symbol_id="sym_c", reference="C1", value="100n"),
            ComponentInstance(instance_id="u2", symbol_id="sym_op", reference="U2", value="OPAMP"),
        ],
        nets=[
            Net(net_id="n_vbus", name="VBUS", nodes=[NetNode(instance_id="u_reg", pin_number="1")]),
            Net(net_id="n_3v3", name="3V3", nodes=[NetNode(instance_id="u_reg", pin_number="2")]),
            Net(net_id="n_gnd", name="GND", nodes=[NetNode(instance_id="u_reg", pin_number="3")]),
        ],
    )


def _sample_board() -> BoardIR:
    return BoardIR(
        board_outline=BoardOutline(shape="rectangle", dimensions_mm={"width": 30.0, "height": 20.0}),
        stackup=[
            StackupLayer(name="F.Cu", kind="copper", thickness_um=35),
            StackupLayer(name="B.Cu", kind="copper", thickness_um=35),
        ],
        footprints=[],
        placement_constraints=[Constraint(constraint_id="c1", kind="clearance", expression=">=0.2mm")],
    )


def test_simulation_service_supports_v1_analyses() -> None:
    schematic = _sample_schematic()

    results = SimulationService().run(schematic)

    analysis_types = {item.analysis_type for item in results}
    assert "regulator_stages" in analysis_types
    assert "filters" in analysis_types
    assert "op_amp_circuits" in analysis_types


def test_review_agent_produces_expected_categories() -> None:
    findings = ReviewAgent(simulation_service=SimulationService()).review(_sample_schematic(), _sample_board())

    categories = {item.category for item in findings}
    assert categories == {
        "power_tree_review",
        "protection_review",
        "grounding_review",
        "layout_risk_review",
    }
    assert all(item.links is not None for item in findings)


def test_design_review_endpoint_returns_advisory_output(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    project = client.post(
        "/projects",
        json={"owner_email": "review@example.com", "name": "design-review"},
    ).json()

    response = client.post(
        f"/projects/{project['id']}/design/review",
        json={
            "schematic_ir": _sample_schematic().model_dump(),
            "board_ir": _sample_board().model_dump(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "not formal signoff" in payload["disclaimer"].lower()
    assert payload["findings"]
    assert payload["simulation_results"]
    assert payload["findings"][0]["is_advisory"] is True
