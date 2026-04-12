from __future__ import annotations

from pathlib import Path

from design_ir.models import (
    BoardIR,
    BoardOutline,
    ComponentInstance,
    Footprint,
    Net,
    NetClass,
    SchematicIR,
    StackupLayer,
    Symbol,
)
from trace_kicad.pcb_compiler import PCBCompiler, write_compiled_board


def _fixture_board() -> tuple[BoardIR, SchematicIR]:
    schematic = SchematicIR(
        symbols=[Symbol(symbol_id="sym_mcu", kind="mcu")],
        component_instances=[ComponentInstance(instance_id="inst_mcu", symbol_id="sym_mcu", reference="U1")],
        nets=[Net(net_id="n1", name="GND"), Net(net_id="n2", name="VBUS")],
    )
    board = BoardIR(
        board_outline=BoardOutline(shape="rectangle", dimensions_mm={"width": 90, "height": 55}),
        stackup=[StackupLayer(name="F.Cu", kind="copper", thickness_um=35), StackupLayer(name="B.Cu", kind="copper", thickness_um=35)],
        footprints=[
            Footprint(
                footprint_id="fp_inst_mcu",
                instance_id="inst_mcu",
                package="QFN48",
                library_ref="Package_QFN:QFN-48",
                placement={"x_mm": 30.0, "y_mm": 20.0, "rotation_deg": 0.0},
                provenance="test",
            )
        ],
        net_classes=[NetClass(name="Default", nets=["GND", "VBUS"], rules={"trace_width_mm": 0.2, "clearance_mm": 0.2})],
    )
    return board, schematic


def test_pcb_compiler_renders_outline_footprints_and_rules(tmp_path: Path) -> None:
    board_ir, schematic_ir = _fixture_board()

    compiled = PCBCompiler().compile(board_ir=board_ir, schematic_ir=schematic_ir, project_name="PCB Test")
    path = write_compiled_board(compiled, tmp_path)

    content = path.read_text(encoding="utf-8")
    assert "kicad_pcb" in content
    assert "Edge.Cuts" in content
    assert 'property "TraceInstanceId" "inst_mcu"' in content
    assert '(net_class "Default" "generated")' in content
