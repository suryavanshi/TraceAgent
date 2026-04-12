from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from design_ir.models import BoardIR, SchematicIR


@dataclass(frozen=True)
class CompiledKiCadBoard:
    pcb_file_name: str
    pcb_file_content: str
    metadata: dict[str, str | int | float]


class PCBCompiler:
    def compile(self, board_ir: BoardIR, schematic_ir: SchematicIR, project_name: str) -> CompiledKiCadBoard:
        safe_name = project_name.replace(" ", "_").lower()
        width = board_ir.board_outline.dimensions_mm.get("width", 100.0)
        height = board_ir.board_outline.dimensions_mm.get("height", 80.0)
        lines = [
            "(kicad_pcb",
            "  (version 20231120)",
            '  (generator "traceagent")',
            "  (general",
            "    (thickness 1.6)",
            "  )",
            "  (layers",
            '    (0 "F.Cu" signal)',
            '    (31 "B.Cu" signal)',
            '    (44 "Edge.Cuts" user)',
            "  )",
        ]
        lines.extend(self._render_nets(schematic_ir))
        lines.extend(self._render_netclasses(board_ir))
        lines.extend(self._render_outline(width, height))
        lines.extend(self._render_mounting_holes(board_ir))
        lines.extend(self._render_footprints(board_ir, schematic_ir))
        lines.append(")\n")

        return CompiledKiCadBoard(
            pcb_file_name=f"{safe_name}.kicad_pcb",
            pcb_file_content="\n".join(lines),
            metadata={
                "shape": board_ir.board_outline.shape,
                "width_mm": width,
                "height_mm": height,
                "footprint_count": len(board_ir.footprints),
                "net_class_count": len(board_ir.net_classes),
                "placement_decision_count": len(board_ir.placement_decisions),
            },
        )

    def _render_nets(self, schematic_ir: SchematicIR) -> list[str]:
        lines = ['  (net 0 "")']
        for index, net in enumerate(sorted(schematic_ir.nets, key=lambda n: n.net_id), start=1):
            name = (net.name or net.net_id).replace('"', "")
            lines.append(f'  (net {index} "{name}")')
        return lines

    def _render_netclasses(self, board_ir: BoardIR) -> list[str]:
        lines: list[str] = []
        for netclass in board_ir.net_classes:
            lines.append(f'  (net_class "{netclass.name}" "generated")')
            for key, value in sorted(netclass.rules.items()):
                lines.append(f'  (rule (name "{netclass.name}_{key}") (constraint {key}) (value {value}))')
            for net_name in netclass.nets:
                lines.append(f'  (add_net "{net_name}")')
        return lines

    def _render_outline(self, width_mm: float, height_mm: float) -> list[str]:
        return [
            f"  (gr_rect (start 0 0) (end {width_mm:.2f} {height_mm:.2f})",
            '    (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts"))',
        ]

    def _render_mounting_holes(self, board_ir: BoardIR) -> list[str]:
        lines: list[str] = []
        for hole in board_ir.mounting_holes:
            lines.extend(
                [
                    f'  (footprint "MountingHole:MountingHole_{hole.diameter_mm:.1f}mm" (layer "F.Cu")',
                    f'    (tstamp "{hole.hole_id}")',
                    f'    (at {hole.x_mm:.2f} {hole.y_mm:.2f})',
                    f'    (property "Reference" "{hole.hole_id.upper()}")',
                    "  )",
                ]
            )
        return lines

    def _render_footprints(self, board_ir: BoardIR, schematic_ir: SchematicIR) -> list[str]:
        by_instance = {instance.instance_id: instance for instance in schematic_ir.component_instances}
        lines: list[str] = []
        for index, footprint in enumerate(sorted(board_ir.footprints, key=lambda item: item.instance_id), start=1):
            x = footprint.placement.get("x_mm", 20.0 + index * 3.0)
            y = footprint.placement.get("y_mm", 20.0 + index * 3.0)
            rotation = footprint.placement.get("rotation_deg", 0.0)
            reference = by_instance.get(footprint.instance_id).reference if footprint.instance_id in by_instance else footprint.instance_id
            lines.extend(
                [
                    f'  (footprint "{footprint.library_ref or footprint.package}" (layer "F.Cu")',
                    f'    (tstamp "{footprint.footprint_id}")',
                    f'    (at {x:.2f} {y:.2f} {rotation:.2f})',
                    f'    (property "Reference" "{reference}")',
                    f'    (property "Value" "{footprint.package}")',
                    f'    (property "TraceInstanceId" "{footprint.instance_id}")',
                    f'    (property "TraceProvenance" "{footprint.provenance}")',
                    "  )",
                ]
            )
        return lines


def write_compiled_board(compiled: CompiledKiCadBoard, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / compiled.pcb_file_name
    path.write_text(compiled.pcb_file_content, encoding="utf-8")
    return path
