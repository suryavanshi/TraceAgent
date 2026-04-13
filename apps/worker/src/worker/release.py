from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from design_ir.models import BoardIR, SchematicIR
from trace_kicad.runner import compile_and_export_project, compile_board_project
from trace_verification import run_kicad_drc, run_kicad_erc

from worker.bom_generator import generate_bom_csv


@dataclass(frozen=True)
class ReleaseBundleResult:
    bundle_name: str
    output_dir: Path
    files: dict[str, str]
    manifest: dict


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_release_bundle(
    *,
    project_name: str,
    version: str,
    snapshot_id: str,
    snapshot_git_commit_hash: str,
    schematic_ir: SchematicIR,
    board_ir: BoardIR,
    output_root: Path,
) -> ReleaseBundleResult:
    deterministic_name = f"{project_name.replace(' ', '_').lower()}_{version}_{snapshot_git_commit_hash[:12]}"
    bundle_dir = output_root / deterministic_name
    bundle_dir.mkdir(parents=True, exist_ok=True)

    exported_paths = compile_and_export_project(schematic_ir=schematic_ir, project_name=project_name, output_dir=bundle_dir / "compiled")
    board_paths = compile_board_project(
        board_ir=board_ir,
        schematic_ir=schematic_ir,
        project_name=project_name,
        output_dir=bundle_dir / "compiled",
    )

    schematic_svg_target = bundle_dir / "schematic" / Path(exported_paths["svg"]).name
    schematic_pdf_target = bundle_dir / "schematic" / Path(exported_paths["pdf"]).name
    pcb_plot_target = bundle_dir / "pcb" / f"{project_name.replace(' ', '_').lower()}_plot.gbr"
    erc_report_target = bundle_dir / "reports" / "erc.json"
    drc_report_target = bundle_dir / "reports" / "drc.json"
    bom_target = bundle_dir / "bom" / "bom.csv"
    pick_place_target = bundle_dir / "assembly" / "pick_and_place.csv"
    fab_gerber_target = bundle_dir / "fabrication" / "gerbers.zip"
    fab_drill_target = bundle_dir / "fabrication" / "drill.drl"

    schematic_svg_target.parent.mkdir(parents=True, exist_ok=True)
    schematic_pdf_target.parent.mkdir(parents=True, exist_ok=True)
    schematic_svg_target.write_text(Path(exported_paths["svg"]).read_text(encoding="utf-8"), encoding="utf-8")
    schematic_pdf_target.write_bytes(Path(exported_paths["pdf"]).read_bytes())

    pcb_payload = Path(board_paths["pcb"]).read_text(encoding="utf-8")
    _write_text(pcb_plot_target, f"; placeholder deterministic PCB plot generated from:\n{pcb_payload}")

    erc_report = run_kicad_erc(Path(exported_paths["project"]))
    drc_report = run_kicad_drc(Path(board_paths["pcb"]))
    _write_text(erc_report_target, json.dumps(erc_report, indent=2, sort_keys=True))
    _write_text(drc_report_target, json.dumps(drc_report, indent=2, sort_keys=True))

    bom_csv = generate_bom_csv(schematic_ir)
    _write_text(bom_target, bom_csv)

    pick_and_place_lines = ["Ref,X(mm),Y(mm),Rotation(deg),Side"]
    for footprint in board_ir.footprints:
        placement = footprint.placement or {"x_mm": 0, "y_mm": 0, "rotation_deg": 0}
        pick_and_place_lines.append(
            f"{footprint.footprint_id},{placement.get('x_mm', 0)},{placement.get('y_mm', 0)},{placement.get('rotation_deg', 0)},Top"
        )
    _write_text(pick_place_target, "\n".join(pick_and_place_lines) + "\n")

    _write_text(fab_gerber_target, "placeholder gerber archive path; replace with real CAM export")
    _write_text(fab_drill_target, "M48\n; placeholder drill file\nM30\n")

    _write_text(bundle_dir / "source" / "schematic_ir.json", json.dumps(schematic_ir.model_dump(), indent=2, sort_keys=True))
    _write_text(bundle_dir / "source" / "board_ir.json", json.dumps(board_ir.model_dump(), indent=2, sort_keys=True))

    tracked_files = [
        schematic_svg_target,
        schematic_pdf_target,
        pcb_plot_target,
        erc_report_target,
        drc_report_target,
        bom_target,
        pick_place_target,
        fab_gerber_target,
        fab_drill_target,
        bundle_dir / "source" / "schematic_ir.json",
        bundle_dir / "source" / "board_ir.json",
    ]

    manifest = {
        "bundle_name": deterministic_name,
        "project_name": project_name,
        "version": version,
        "snapshot": {
            "snapshot_id": snapshot_id,
            "git_commit_hash": snapshot_git_commit_hash,
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "contents": [
            {
                "path": str(path.relative_to(bundle_dir)),
                "sha256": _file_sha256(path),
            }
            for path in tracked_files
        ],
    }
    manifest_path = bundle_dir / "manifest.json"
    _write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True))

    return ReleaseBundleResult(
        bundle_name=deterministic_name,
        output_dir=bundle_dir,
        files={
            "manifest": str(manifest_path),
            "bom": str(bom_target),
            "pick_and_place": str(pick_place_target),
            "erc": str(erc_report_target),
            "drc": str(drc_report_target),
        },
        manifest=manifest,
    )
