from __future__ import annotations

from pathlib import Path

from design_ir.models import BoardIR, BoardOutline, Net, RoutingIntent, SchematicIR
from trace_kicad.routing import RoutingPlanner, SpecctraSessionIO


def _fixture() -> tuple[SchematicIR, BoardIR]:
    schematic = SchematicIR(
        nets=[
            Net(net_id="n1", name="USB_D_P"),
            Net(net_id="n2", name="MCLK"),
            Net(net_id="n3", name="VBUS"),
            Net(net_id="n4", name="ADC_REF"),
            Net(net_id="n5", name="GPIO_A"),
        ]
    )
    board = BoardIR(board_outline=BoardOutline(shape="rectangle", dimensions_mm={"width": 40, "height": 30}), routing_intents=[RoutingIntent(net_or_group="GPIO_A", intent="critical")])
    return schematic, board


def test_routing_planner_classifies_and_restricts_autoroute() -> None:
    schematic, board = _fixture()
    plan = RoutingPlanner().classify(schematic_ir=schematic, board_ir=board)

    by_net = {entry.net_name: entry for entry in plan.nets}
    assert by_net["USB_D_P"].routing_class == "critical"
    assert by_net["MCLK"].routing_class == "clocks"
    assert by_net["VBUS"].routing_class == "power"
    assert by_net["ADC_REF"].routing_class == "analog-sensitive"
    assert by_net["GPIO_A"].routing_class == "critical"
    assert by_net["VBUS"].autoroute_allowed
    assert not by_net["USB_D_P"].autoroute_allowed


def test_specctra_export_and_import_session(tmp_path: Path) -> None:
    schematic, board = _fixture()
    plan = RoutingPlanner().classify(schematic_ir=schematic, board_ir=board)
    adapter = SpecctraSessionIO()

    exported = adapter.export_dsn(
        project_file=tmp_path / "demo.kicad_pro",
        pcb_file=tmp_path / "demo.kicad_pcb",
        output_dir=tmp_path,
        routing_plan=plan,
    )
    assert exported.dsn_path.exists()
    assert exported.plan_path.exists()

    ses_path = tmp_path / "demo.ses"
    ses_path.write_text("route VBUS\nroute GPIO_A\n", encoding="utf-8")
    imported = adapter.import_ses(ses_path=ses_path, routing_plan=plan)
    assert "VBUS" in imported.routed_nets
    assert "USB_D_P" in imported.unrouted_nets
