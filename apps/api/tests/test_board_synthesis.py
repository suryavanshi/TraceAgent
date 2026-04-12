from __future__ import annotations

import json
from pathlib import Path

from api.board_synthesis import BoardIRGenerator, BoardRulesBuilder
from api.placement_engine import DeterministicPlacementEngine
from design_ir.models import BoardIR, CircuitSpec, ComponentInstance, Constraint, FixedEdgeConnector, NamedObject, Net, SchematicIR, Symbol


def _spec() -> CircuitSpec:
    return CircuitSpec(
        product_name="Board synth",
        summary="Board synthesis target",
        target_board_type="sensor",
        mechanical_constraints=["Width 120 mm", "Height 70 mm"],
        interfaces=[NamedObject(name="USB")],
    )


def _schematic() -> SchematicIR:
    return SchematicIR(
        symbols=[Symbol(symbol_id="sym_usb", kind="connector"), Symbol(symbol_id="sym_mcu", kind="mcu")],
        component_instances=[
            ComponentInstance(
                instance_id="inst_usb",
                symbol_id="sym_usb",
                reference="J1",
                properties={"package": "USB_C_Receptacle", "footprint_library": "Connector_USB"},
            ),
            ComponentInstance(instance_id="inst_mcu", symbol_id="sym_mcu", reference="U1", properties={"package": "QFN48"}),
        ],
        nets=[Net(net_id="net_gnd", name="GND"), Net(net_id="net_vbus", name="VBUS")],
    )


def test_board_rules_builder_derives_expected_classes() -> None:
    builder = BoardRulesBuilder()
    net_classes, design_rules, zones = builder.build(_spec(), _schematic())

    assert any(item.name == "Default" for item in net_classes)
    assert any(item.name == "Power" for item in net_classes)
    assert any(rule.kind == "via" for rule in design_rules)
    assert zones and zones[0].region_type == "copper_zone"


def test_board_ir_generator_keeps_instance_linkage_and_connectors() -> None:
    board = BoardIRGenerator().generate(_spec(), _schematic())

    assert board.board_outline.dimensions_mm["width"] == 120
    assert board.board_outline.dimensions_mm["height"] == 70
    assert sorted(fp.instance_id for fp in board.footprints) == ["inst_mcu", "inst_usb"]
    assert any(conn.instance_id == "inst_usb" for conn in board.fixed_edge_connectors)
    assert board.mounting_holes
    assert board.placement_decisions
    assert board.placement_visualization.get("overlays")


def test_placement_engine_is_deterministic_and_tracks_rationale() -> None:
    generator = BoardIRGenerator()
    board_a = generator.generate(_spec(), _schematic())
    board_b = generator.generate(_spec(), _schematic())

    placements_a = [fp.placement for fp in sorted(board_a.footprints, key=lambda item: item.instance_id)]
    placements_b = [fp.placement for fp in sorted(board_b.footprints, key=lambda item: item.instance_id)]

    assert placements_a == placements_b
    assert len(board_a.placement_decisions) == len(board_a.footprints)
    assert all(decision.rationale for decision in board_a.placement_decisions)


def test_placement_constraints_supported() -> None:
    schematic = SchematicIR(
        symbols=[Symbol(symbol_id="sym_conn", kind="connector"), Symbol(symbol_id="sym_dbg", kind="header")],
        component_instances=[
            ComponentInstance(instance_id="conn1", symbol_id="sym_conn", reference="J1", properties={"package": "USB_C"}),
            ComponentInstance(instance_id="dbg1", symbol_id="sym_dbg", reference="J2", properties={"package": "HDR_2x5"}),
        ],
        nets=[Net(net_id="n1", name="VBUS"), Net(net_id="n2", name="GND")],
    )
    board = BoardIR(
        board_outline={"shape": "rectangle", "dimensions_mm": {"width": 80, "height": 60}},
        stackup=[],
        footprints=[
            {"footprint_id": "fp_conn1", "instance_id": "conn1", "package": "USB_C", "library_ref": "X:Y"},
            {"footprint_id": "fp_dbg1", "instance_id": "dbg1", "package": "HDR_2x5", "library_ref": "X:Y"},
        ],
        mounting_holes=[],
        fixed_edge_connectors=[FixedEdgeConnector(connector_id="edge_conn1", instance_id="conn1", edge="bottom", offset_mm=8)],
        placement_constraints=[
            Constraint(constraint_id="c1", kind="edge_locked", expression="instance_id=conn1;edge=bottom;offset_mm=8"),
            Constraint(constraint_id="c2", kind="near_component", expression="instance_id=dbg1;anchor_instance_id=conn1;distance_mm=5"),
            Constraint(constraint_id="c3", kind="distance_limit", expression="instance_id=dbg1;anchor_instance_id=conn1;max_distance_mm=5"),
            Constraint(constraint_id="c4", kind="orientation_preference", expression="instance_id=dbg1;rotation_deg=90"),
            Constraint(constraint_id="c5", kind="region_preference", expression="instance_id=dbg1;x_min=10;x_max=40;y_min=10;y_max=30"),
        ],
        design_rules=[],
        net_classes=[],
        keepouts=[],
        zones=[],
        routing_intents=[],
    )
    placed = DeterministicPlacementEngine().place(board, schematic)
    conn = next(item for item in placed.footprints if item.instance_id == "conn1")
    dbg = next(item for item in placed.footprints if item.instance_id == "dbg1")

    assert conn.placement["y_mm"] == 55
    assert dbg.placement["rotation_deg"] == 90
    assert 10 <= dbg.placement["x_mm"] <= 40
    assert 10 <= dbg.placement["y_mm"] <= 30


def test_placement_engine_reference_designs_have_overlay_metadata() -> None:
    fixture_dir = Path(__file__).resolve().parents[3] / "packages" / "design-ir" / "tests" / "fixtures"
    fixture_names = ["example_design_sensor_node.json", "example_design_gateway.json"]
    for fixture_name in fixture_names:
        fixture = json.loads((fixture_dir / fixture_name).read_text(encoding="utf-8"))
        circuit_spec = CircuitSpec.model_validate(fixture["circuit_spec"])
        schematic = SchematicIR.model_validate(fixture["schematic_ir"])
        board = BoardIRGenerator().generate(circuit_spec, schematic)
        assert board.placement_decisions
        assert board.placement_visualization.get("overlays")
