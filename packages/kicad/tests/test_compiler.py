from __future__ import annotations

import json
from pathlib import Path

from design_ir.models import SchematicIR
from trace_kicad.runner import compile_and_export_project


def _load_fixture(name: str) -> tuple[str, SchematicIR]:
    fixture_path = Path(__file__).resolve().parents[2] / "design-ir" / "tests" / "fixtures" / name
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    product_name = payload["circuit_spec"]["product_name"]
    return product_name, SchematicIR.model_validate(payload["schematic_ir"])


def test_compiler_exports_expected_artifacts_for_sensor_node(tmp_path: Path) -> None:
    project_name, schematic_ir = _load_fixture("example_design_sensor_node.json")

    output = compile_and_export_project(schematic_ir, project_name, tmp_path)

    assert Path(output["project"]).exists()
    assert Path(output["schematic"]).exists()
    assert Path(output["sym_lib_table"]).exists()
    assert Path(output["svg"]).exists()
    assert Path(output["pdf"]).exists()
    assert "kicad_sch" in Path(output["schematic"]).read_text(encoding="utf-8")


def test_compiler_is_deterministic_for_same_input(tmp_path: Path) -> None:
    project_name, schematic_ir = _load_fixture("example_design_gateway.json")

    first = compile_and_export_project(schematic_ir, project_name, tmp_path / "run1")
    second = compile_and_export_project(schematic_ir, project_name, tmp_path / "run2")

    first_sch = Path(first["schematic"]).read_text(encoding="utf-8")
    second_sch = Path(second["schematic"]).read_text(encoding="utf-8")
    first_pro = Path(first["project"]).read_text(encoding="utf-8")
    second_pro = Path(second["project"]).read_text(encoding="utf-8")

    assert first_sch == second_sch
    assert first_pro == second_pro
