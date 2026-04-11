from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from design_ir.models import ComponentInstance, Net, NetLabel, SchematicIR, Symbol


@dataclass(frozen=True)
class SymbolPlacement:
    instance_id: str
    reference: str
    value: str
    x: float
    y: float
    region: str


@dataclass(frozen=True)
class CompiledKiCadProject:
    project_file_name: str
    schematic_file_name: str
    project_file_content: str
    schematic_file_content: str
    sym_lib_table_content: str


class SchematicLayoutHelper:
    """Deterministic block-based placement helper for readability."""

    _REGION_ORDER = {
        "power": 0,
        "io": 1,
        "control": 2,
        "processing": 3,
        "sensing": 4,
        "passive": 5,
        "other": 6,
    }

    _REGION_X = {
        "power": 20.0,
        "io": 70.0,
        "control": 120.0,
        "processing": 170.0,
        "sensing": 220.0,
        "passive": 270.0,
        "other": 320.0,
    }

    def place(self, schematic_ir: SchematicIR) -> list[SymbolPlacement]:
        components = sorted(schematic_ir.component_instances, key=lambda c: (self._region_for(c), c.reference, c.instance_id))
        region_offsets: dict[str, int] = {}
        placements: list[SymbolPlacement] = []
        for component in components:
            region = self._region_for(component)
            row = region_offsets.get(region, 0)
            region_offsets[region] = row + 1
            x = self._REGION_X.get(region, self._REGION_X["other"])
            y = 40.0 + (row * 30.0)
            placements.append(
                SymbolPlacement(
                    instance_id=component.instance_id,
                    reference=component.reference,
                    value=component.value or component.instance_id,
                    x=x,
                    y=y,
                    region=region,
                )
            )
        return placements

    def _region_for(self, component: ComponentInstance) -> str:
        role = component.properties.get("functional_role", "").lower()
        symbol_kind = component.symbol_id.lower()
        value = (component.value or "").lower()
        joined = " ".join((role, symbol_kind, value, component.reference.lower()))

        if any(token in joined for token in ("gnd", "vcc", "vdd", "vbus", "buck", "ldo", "reg")):
            return "power"
        if any(token in joined for token in ("usb", "conn", "uart", "header", "j")):
            return "io"
        if any(token in joined for token in ("mcu", "microcontroller", "cpu", "esp", "stm32")):
            return "processing"
        if any(token in joined for token in ("sensor", "adc", "temp", "imu")):
            return "sensing"
        if any(token in joined for token in ("pullup", "res", "cap", "ind", "passive", "r", "c")):
            return "passive"
        if any(token in joined for token in ("enable", "supervisor", "reset")):
            return "control"
        return "other"


class SchematicCompiler:
    def __init__(self, layout_helper: SchematicLayoutHelper | None = None) -> None:
        self.layout_helper = layout_helper or SchematicLayoutHelper()

    def compile(self, schematic_ir: SchematicIR, project_name: str) -> CompiledKiCadProject:
        safe_name = project_name.replace(" ", "_").lower()
        placements = self.layout_helper.place(schematic_ir)
        symbol_lookup = {symbol.symbol_id: symbol for symbol in schematic_ir.symbols}

        project_json = {
            "meta": {"filename": f"{safe_name}.kicad_pro", "version": 1},
            "schematic": {"page_layout_descr_file": ""},
            "libraries": {"pinned_symbol_libs": sorted(self._used_symbol_libraries(schematic_ir.symbols))},
        }

        schematic_lines: list[str] = [
            "(kicad_sch",
            "  (version 20231120)",
            '  (generator "traceagent")',
            f'  (title_block (title "{project_name}"))',
            "  (paper \"A4\")",
            "",
        ]

        for placement in sorted(placements, key=lambda p: (self.layout_helper._REGION_ORDER.get(p.region, 99), p.reference, p.instance_id)):
            symbol_ref = next((inst.symbol_id for inst in schematic_ir.component_instances if inst.instance_id == placement.instance_id), placement.reference)
            symbol = symbol_lookup.get(symbol_ref)
            lib_ref = (symbol.library_ref if symbol and symbol.library_ref else "Device:Generic")
            schematic_lines.extend(
                [
                    f'  (symbol (lib_id "{lib_ref}") (at {placement.x:.2f} {placement.y:.2f} 0)',
                    f'    (property "Reference" "{placement.reference}" (at {placement.x:.2f} {placement.y - 2:.2f} 0))',
                    f'    (property "Value" "{placement.value}" (at {placement.x:.2f} {placement.y + 2:.2f} 0))',
                    f'    (property "TraceRegion" "{placement.region}" (at {placement.x:.2f} {placement.y + 4:.2f} 0))',
                    "  )",
                ]
            )

        for label in self._stable_labels(schematic_ir.nets, schematic_ir.net_labels):
            schematic_lines.append(f'  (global_label "{label}" (shape input) (at 10 10 0) (fields_autoplaced))')

        schematic_lines.append(")\n")

        sym_lib_table_content = self._render_sym_lib_table(self._used_symbol_libraries(schematic_ir.symbols))
        return CompiledKiCadProject(
            project_file_name=f"{safe_name}.kicad_pro",
            schematic_file_name=f"{safe_name}.kicad_sch",
            project_file_content=json.dumps(project_json, indent=2, sort_keys=True) + "\n",
            schematic_file_content="\n".join(schematic_lines),
            sym_lib_table_content=sym_lib_table_content,
        )

    def _used_symbol_libraries(self, symbols: Iterable[Symbol]) -> set[str]:
        libraries = set()
        for symbol in symbols:
            if symbol.library_ref and ":" in symbol.library_ref:
                libraries.add(symbol.library_ref.split(":", 1)[0])
        if not libraries:
            libraries.add("Device")
        return libraries

    def _stable_labels(self, nets: list[Net], labels: list[NetLabel]) -> list[str]:
        by_id = {label.net_id: label.label for label in labels}
        result = []
        for net in sorted(nets, key=lambda n: n.net_id):
            result.append(self._normalize_label(by_id.get(net.net_id) or net.name or net.net_id))
        return sorted(set(result))

    def _normalize_label(self, label: str) -> str:
        return label.upper().replace(" ", "_")

    def _render_sym_lib_table(self, libraries: set[str]) -> str:
        rows = ["(sym_lib_table"]
        for lib in sorted(libraries):
            rows.append(f'  (lib (name "{lib}")(type "KiCad")(uri "${{KICAD7_SYMBOL_DIR}}/{lib}.kicad_sym")(options "")(descr ""))')
        rows.append(")\n")
        return "\n".join(rows)


def write_compiled_project(compiled: CompiledKiCadProject, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    project_path = output_dir / compiled.project_file_name
    schematic_path = output_dir / compiled.schematic_file_name
    sym_lib_table_path = output_dir / "sym-lib-table"

    project_path.write_text(compiled.project_file_content, encoding="utf-8")
    schematic_path.write_text(compiled.schematic_file_content, encoding="utf-8")
    sym_lib_table_path.write_text(compiled.sym_lib_table_content, encoding="utf-8")

    return {
        "project": project_path,
        "schematic": schematic_path,
        "sym_lib_table": sym_lib_table_path,
    }
