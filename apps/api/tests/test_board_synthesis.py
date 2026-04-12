from __future__ import annotations

from api.board_synthesis import BoardIRGenerator, BoardRulesBuilder
from design_ir.models import CircuitSpec, ComponentInstance, NamedObject, Net, SchematicIR, Symbol


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
