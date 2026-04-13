from __future__ import annotations

import json
from pathlib import Path

from design_ir.models import BoardIR, SchematicIR
from trace_kicad.routing import FreeroutingAdapter, FreeroutingRunResult, RoutingPlanner, SpecctraSessionIO
from trace_verification import explain_finding, normalize_report, run_kicad_erc


def run_freerouting_job(
    *,
    project_file: str,
    pcb_file: str,
    schematic_ir: SchematicIR,
    board_ir: BoardIR,
    output_dir: str,
    planner: RoutingPlanner | None = None,
    specctra_io: SpecctraSessionIO | None = None,
    freerouting: FreeroutingAdapter | None = None,
) -> FreeroutingRunResult:
    planner = planner or RoutingPlanner()
    specctra_io = specctra_io or SpecctraSessionIO()
    freerouting = freerouting or FreeroutingAdapter()

    workspace = Path(output_dir)
    workspace.mkdir(parents=True, exist_ok=True)

    routing_plan = planner.classify(schematic_ir=schematic_ir, board_ir=board_ir)
    exported = specctra_io.export_dsn(
        project_file=Path(project_file),
        pcb_file=Path(pcb_file),
        output_dir=workspace,
        routing_plan=routing_plan,
    )
    ses_path = workspace / f"{Path(pcb_file).stem}.ses"
    log_path = workspace / "freerouting.log"
    ok = freerouting.run_cli(dsn_path=exported.dsn_path, ses_path=ses_path, log_path=log_path)

    imported = specctra_io.import_ses(ses_path=ses_path, routing_plan=routing_plan)

    raw_output = run_kicad_erc(Path(project_file))
    normalized_output = normalize_report(raw_output)
    explanations = [{"code": finding["code"], "plain_english": explain_finding(finding)} for finding in normalized_output.get("findings", [])]
    verification = {
        "status": "completed" if raw_output.get("status") == "completed" else "failed",
        "raw_output": raw_output,
        "normalized_output": normalized_output,
        "explanations": explanations,
    }
    (workspace / "verification.json").write_text(json.dumps(verification, indent=2, sort_keys=True), encoding="utf-8")

    return FreeroutingRunResult(
        status="completed" if ok else "failed",
        dsn_path=exported.dsn_path,
        ses_path=imported.ses_path,
        log_path=log_path,
        routed_nets=imported.routed_nets,
        unrouted_nets=imported.unrouted_nets,
        verification=verification,
    )
