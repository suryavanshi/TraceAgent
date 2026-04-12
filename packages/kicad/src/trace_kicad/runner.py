from __future__ import annotations

from pathlib import Path

from design_ir.models import BoardIR, SchematicIR

from trace_kicad.compiler import SchematicCompiler, write_compiled_project
from trace_kicad.pcb_compiler import PCBCompiler, write_compiled_board
from trace_kicad.export import export_schematic_pdf, export_schematic_svg


def run_kicad_job(job_name: str) -> dict[str, str]:
    return {"job": job_name, "status": "queued"}


def compile_and_export_project(schematic_ir: SchematicIR, project_name: str, output_dir: Path) -> dict[str, str]:
    compiler = SchematicCompiler()
    compiled = compiler.compile(schematic_ir=schematic_ir, project_name=project_name)
    file_paths = write_compiled_project(compiled, output_dir)
    placements = compiler.layout_helper.place(schematic_ir)

    svg_path = output_dir / f"{project_name.replace(' ', '_').lower()}.svg"
    pdf_path = output_dir / f"{project_name.replace(' ', '_').lower()}.pdf"
    export_schematic_svg(file_paths["schematic"], svg_path, placements)
    export_schematic_pdf(file_paths["schematic"], pdf_path, placements)

    return {
        "project": str(file_paths["project"]),
        "schematic": str(file_paths["schematic"]),
        "sym_lib_table": str(file_paths["sym_lib_table"]),
        "svg": str(svg_path),
        "pdf": str(pdf_path),
    }


def compile_board_project(board_ir: BoardIR, schematic_ir: SchematicIR, project_name: str, output_dir: Path) -> dict[str, str]:
    compiler = PCBCompiler()
    compiled_board = compiler.compile(board_ir=board_ir, schematic_ir=schematic_ir, project_name=project_name)
    pcb_path = write_compiled_board(compiled_board, output_dir)
    return {
        "pcb": str(pcb_path),
    }
