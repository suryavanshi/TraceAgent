from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import Base, engine, get_db
from api.git_snapshots import GitSnapshotRepository
from api.models import DesignSnapshot, Project, User, VerificationRun
from api.requirements_agent import RequirementsAgent, RequirementsChatMessage as AgentChatMessage, RuleBasedRequirementsProvider
from api.part_catalog import LocalCuratedPartCatalog
from api.part_resolver import PartConstraint, PartResolver
from api.board_synthesis import BoardIRGenerator
from api.schematic_synthesis import SchematicSynthesisAgent, SelectedPart
from api.schemas import (
    ProjectCreate,
    ProjectResponse,
    SnapshotCreate,
    SnapshotResponse,
    SnapshotRevertResponse,
    RequirementsDeriveRequest,
    RequirementsDeriveResponse,
    PartReviewRequest,
    PartReviewResponse,
    PartReviewBlock,
    PartReviewCandidate,
    SchematicSynthesisRequest,
    SchematicSynthesisResponse,
    SchematicLintWarningPayload,
    VerificationRunDetailResponse,
    VerificationRunResponse,
)
from api.storage import LocalFilesystemStorage
from trace_kicad.runner import compile_and_export_project, compile_board_project
from trace_kicad.routing import RoutingPlanner
from trace_verification import (
    explain_finding,
    normalize_verification_suite,
    run_kicad_drc,
    run_kicad_erc,
    run_manufacturability_checks,
)

app = FastAPI(title="TraceAgent API", version="0.1.0")

STORAGE_BASE = os.getenv("ARTIFACT_STORAGE_BASE", "/tmp/traceagent/artifacts")
SNAPSHOT_BASE = os.getenv("SNAPSHOT_REPO_BASE", "/tmp/traceagent/snapshots")
storage = LocalFilesystemStorage(STORAGE_BASE)

part_catalog = LocalCuratedPartCatalog()
part_resolver = PartResolver(part_catalog)
schematic_synthesis_agent = SchematicSynthesisAgent()
board_ir_generator = BoardIRGenerator()
routing_planner = RoutingPlanner()


def get_requirements_agent() -> RequirementsAgent:
    return RequirementsAgent(provider=RuleBasedRequirementsProvider())


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api", "version": app.version}


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    return {"status": "ok", "service": "api", "checks": "pending"}


@app.post("/projects", response_model=ProjectResponse)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    user = db.scalar(select(User).where(User.email == payload.owner_email))
    if user is None:
        user = User(email=payload.owner_email, display_name=payload.owner_display_name)
        db.add(user)
        db.flush()

    artifact_dir = f"projects/{user.id}/{payload.name}"
    snapshot_repo_dir = str(Path(SNAPSHOT_BASE) / str(user.id) / payload.name)

    project = Project(
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
        artifact_root_dir=artifact_dir,
        snapshot_repo_dir=snapshot_repo_dir,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    GitSnapshotRepository(project.snapshot_repo_dir)
    return project


@app.get("/projects", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())).all())


@app.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.post("/projects/{project_id}/snapshots", response_model=SnapshotResponse)
def create_snapshot(project_id: UUID, payload: SnapshotCreate, db: Session = Depends(get_db)) -> DesignSnapshot:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    artifact_dir = f"{project.artifact_root_dir}/snapshots/{payload.title.replace(' ', '_').lower()}"
    for file in payload.files:
        storage.write_text(artifact_dir, file.path, file.content)
        Path(project.snapshot_repo_dir).mkdir(parents=True, exist_ok=True)
        target = Path(project.snapshot_repo_dir) / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")

    git_repo = GitSnapshotRepository(project.snapshot_repo_dir)
    commit_hash = git_repo.commit_all(f"snapshot: {payload.title}")
    snapshot = DesignSnapshot(
        project_id=project.id,
        title=payload.title,
        notes=payload.notes,
        artifact_dir=artifact_dir,
        git_commit_hash=commit_hash,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@app.get("/projects/{project_id}/snapshots", response_model=list[SnapshotResponse])
def list_snapshots(project_id: UUID, db: Session = Depends(get_db)) -> list[DesignSnapshot]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list(
        db.scalars(select(DesignSnapshot).where(DesignSnapshot.project_id == project_id).order_by(DesignSnapshot.created_at.desc())).all()
    )


@app.post("/projects/{project_id}/snapshots/{snapshot_id}/revert", response_model=SnapshotRevertResponse)
def revert_snapshot(project_id: UUID, snapshot_id: UUID, db: Session = Depends(get_db)) -> SnapshotRevertResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    snapshot = db.get(DesignSnapshot, snapshot_id)
    if snapshot is None or snapshot.project_id != project.id:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    git_repo = GitSnapshotRepository(project.snapshot_repo_dir)
    current_hash = git_repo.revert_to(snapshot.git_commit_hash)
    return SnapshotRevertResponse(
        project_id=project.id,
        reverted_to_snapshot_id=snapshot.id,
        git_commit_hash=current_hash,
    )


@app.post("/projects/{project_id}/requirements/derive", response_model=RequirementsDeriveResponse)
def derive_project_requirements(
    project_id: UUID,
    payload: RequirementsDeriveRequest,
    db: Session = Depends(get_db),
    agent: RequirementsAgent = Depends(get_requirements_agent),
) -> RequirementsDeriveResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    result = agent.derive(
        chat_history=[AgentChatMessage.model_validate(message.model_dump()) for message in payload.chat_history],
        latest_user_request=payload.latest_user_request,
    )
    return RequirementsDeriveResponse(
        proposed_circuit_spec=result.proposed_circuit_spec.model_dump(),
        summary=result.summary,
        open_questions=result.open_questions,
    )


@app.post("/projects/{project_id}/parts/review", response_model=PartReviewResponse)
def review_project_parts(
    project_id: UUID,
    payload: PartReviewRequest,
    db: Session = Depends(get_db),
) -> PartReviewResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    constraints = {
        role: PartConstraint(
            package=constraint.package,
            min_voltage_v=constraint.min_voltage_v,
            max_voltage_v=constraint.max_voltage_v,
            min_current_a=constraint.min_current_a,
            interface=constraint.interface,
        )
        for role, constraint in payload.constraints_by_role.items()
    }

    result = part_resolver.review(circuit_spec=payload.circuit_spec, constraints=constraints)
    return PartReviewResponse(
        block_reviews=[
            PartReviewBlock(
                functional_block=review.functional_block,
                candidates=[
                    PartReviewCandidate(
                        mpn=candidate.part.mpn,
                        functional_role=candidate.functional_role,
                        confidence=candidate.confidence,
                        rationale=candidate.rationale,
                        symbol_ref=candidate.part.symbol_ref.model_dump(),
                        footprint_ref=candidate.part.footprint_ref.model_dump(),
                        package=candidate.part.package.name,
                    )
                    for candidate in review.candidates
                ],
            )
            for review in result.block_reviews
        ]
    )


@app.post("/projects/{project_id}/schematic/synthesize", response_model=SchematicSynthesisResponse)
def synthesize_project_schematic(
    project_id: UUID,
    payload: SchematicSynthesisRequest,
    db: Session = Depends(get_db),
) -> SchematicSynthesisResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    synthesis = schematic_synthesis_agent.synthesize(
        circuit_spec=payload.circuit_spec,
        selected_parts=[SelectedPart.model_validate(part.model_dump()) for part in payload.selected_parts],
    )

    artifact_dir = f"{project.artifact_root_dir}/generated"
    relative_path = "schematic_ir/schematic_ir.json"
    saved_path = storage.write_text(artifact_dir, relative_path, json.dumps(synthesis.model_dump(), indent=2, sort_keys=True))
    board_ir = board_ir_generator.generate(circuit_spec=payload.circuit_spec, schematic_ir=synthesis.schematic_ir)
    board_ir_path = storage.write_text(
        artifact_dir,
        "board_ir/board_ir.json",
        json.dumps(board_ir.model_dump(), indent=2, sort_keys=True),
    )

    with tempfile.TemporaryDirectory(prefix="traceagent_kicad_") as temp_dir:
        compiled_paths = compile_and_export_project(
            schematic_ir=synthesis.schematic_ir,
            project_name=project.name,
            output_dir=Path(temp_dir),
        )
        compiled_board_paths = compile_board_project(
            board_ir=board_ir,
            schematic_ir=synthesis.schematic_ir,
            project_name=project.name,
            output_dir=Path(temp_dir),
        )

        kicad_project_content = Path(compiled_paths["project"]).read_text(encoding="utf-8")
        kicad_schematic_content = Path(compiled_paths["schematic"]).read_text(encoding="utf-8")
        kicad_sym_lib_table_content = Path(compiled_paths["sym_lib_table"]).read_text(encoding="utf-8")
        kicad_svg_content = Path(compiled_paths["svg"]).read_text(encoding="utf-8")
        kicad_pdf_bytes = Path(compiled_paths["pdf"]).read_bytes()
        kicad_pcb_content = Path(compiled_board_paths["pcb"]).read_text(encoding="utf-8")

    project_file_name = Path(compiled_paths["project"]).name
    schematic_file_name = Path(compiled_paths["schematic"]).name
    svg_file_name = Path(compiled_paths["svg"]).name
    pdf_file_name = Path(compiled_paths["pdf"]).name
    pcb_file_name = Path(compiled_board_paths["pcb"]).name

    kicad_project_path = storage.write_text(artifact_dir, f"kicad/{project_file_name}", kicad_project_content)
    kicad_schematic_path = storage.write_text(artifact_dir, f"kicad/{schematic_file_name}", kicad_schematic_content)
    kicad_sym_lib_table_path = storage.write_text(artifact_dir, "kicad/sym-lib-table", kicad_sym_lib_table_content)
    kicad_pcb_path = storage.write_text(artifact_dir, f"kicad/{pcb_file_name}", kicad_pcb_content)
    schematic_svg_path = storage.write_text(artifact_dir, f"exports/{svg_file_name}", kicad_svg_content)

    pdf_target = Path(STORAGE_BASE) / artifact_dir / "exports" / pdf_file_name
    pdf_target.parent.mkdir(parents=True, exist_ok=True)
    pdf_target.write_bytes(kicad_pdf_bytes)
    schematic_pdf_path = str(pdf_target)

    routing_plan = routing_planner.classify(schematic_ir=synthesis.schematic_ir, board_ir=board_ir)
    autoroute_targets = routing_plan.autoroute_targets()

    return SchematicSynthesisResponse(
        schematic_ir=synthesis.schematic_ir,
        board_ir=board_ir,
        power_tree=[edge.model_dump() for edge in synthesis.power_tree],
        support_passives=synthesis.support_passives,
        protection_circuitry=synthesis.protection_circuitry,
        programming_interfaces=synthesis.programming_interfaces,
        decoupling_recommendations=[item.model_dump() for item in synthesis.decoupling_recommendations],
        warnings=[SchematicLintWarningPayload.model_validate(w.model_dump()) for w in synthesis.warnings],
        provenance=[item.model_dump() for item in synthesis.provenance],
        saved_path=saved_path,
        kicad_project_path=kicad_project_path,
        kicad_schematic_path=kicad_schematic_path,
        kicad_sym_lib_table_path=kicad_sym_lib_table_path,
        schematic_svg_path=schematic_svg_path,
        schematic_pdf_path=schematic_pdf_path,
        schematic_svg=kicad_svg_content,
        board_ir_path=board_ir_path,
        kicad_pcb_path=kicad_pcb_path,
        board_metadata={
            "shape": board_ir.board_outline.shape,
            "width_mm": board_ir.board_outline.dimensions_mm.get("width", 0),
            "height_mm": board_ir.board_outline.dimensions_mm.get("height", 0),
            "footprints": len(board_ir.footprints),
            "mounting_holes": len(board_ir.mounting_holes),
            "stackup_layers": len(board_ir.stackup),
            "placement_decisions": len(board_ir.placement_decisions),
            "placement_overlay": board_ir.placement_visualization,
            "routing_plan_summary": routing_plan.summary(),
            "autoroute_default_policy": "non-critical-only",
            "critical_nets_reserved_for_manual": [entry.net_name for entry in routing_plan.nets if entry.routing_class == "critical"],
            "routing_state": {
                "routed_count": 0,
                "unrouted_count": len(autoroute_targets),
                "eligible_autoroute_nets": autoroute_targets,
                "verification_required": True,
            },
        },
    )


def _run_project_verification(project: Project) -> tuple[dict, dict, list[dict], str]:
    stem = project.name.replace(" ", "_").lower()
    generated_dir = Path(STORAGE_BASE) / project.artifact_root_dir / "generated"
    project_file = generated_dir / "kicad" / f"{stem}.kicad_pro"
    pcb_file = generated_dir / "kicad" / f"{stem}.kicad_pcb"

    raw_erc = run_kicad_erc(project_file)
    raw_drc = run_kicad_drc(pcb_file)
    raw_manufacturability = run_manufacturability_checks(
        pcb_file,
        current_target_amps=float(os.getenv("MANUFACTURABILITY_CURRENT_TARGET_A", "1.0")),
    )

    raw_output = {"erc": raw_erc, "drc": raw_drc, "manufacturability": raw_manufacturability}
    normalized_output = normalize_verification_suite(raw_output)
    explanations = [{"code": finding["code"], "plain_english": explain_finding(finding)} for finding in normalized_output.get("findings", [])]
    run_status = "completed" if all(item.get("status") == "completed" for item in [raw_erc, raw_drc, raw_manufacturability]) else "failed"
    return raw_output, normalized_output, explanations, run_status


@app.post("/projects/{project_id}/verification-runs", response_model=VerificationRunDetailResponse)
def create_verification_run(project_id: UUID, db: Session = Depends(get_db)) -> VerificationRunDetailResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    raw_output, normalized_output, explanations, run_status = _run_project_verification(project)
    artifact_dir = f"{project.artifact_root_dir}/verification"
    run_prefix = f"run_{uuid4()}"
    raw_output_artifact_path = storage.write_text(
        artifact_dir,
        f"{run_prefix}_raw.json",
        json.dumps(raw_output, indent=2, sort_keys=True),
    )
    normalized_output_artifact_path = storage.write_text(
        artifact_dir,
        f"{run_prefix}_normalized.json",
        json.dumps(normalized_output, indent=2, sort_keys=True),
    )
    explanation_artifact_path = storage.write_text(
        artifact_dir,
        f"{run_prefix}_explanations.json",
        json.dumps(explanations, indent=2, sort_keys=True),
    )

    verification_run = VerificationRun(
        project_id=project.id,
        snapshot_id=None,
        status=run_status,
        report_artifact_path=normalized_output_artifact_path,
        raw_output_artifact_path=raw_output_artifact_path,
        normalized_output_artifact_path=normalized_output_artifact_path,
        explanation_artifact_path=explanation_artifact_path,
    )
    db.add(verification_run)
    db.commit()
    db.refresh(verification_run)

    return VerificationRunDetailResponse(
        **VerificationRunResponse.model_validate(verification_run, from_attributes=True).model_dump(),
        raw_output=raw_output,
        normalized_output=normalized_output,
        explanations=explanations,
    )


@app.get("/projects/{project_id}/verification-runs", response_model=list[VerificationRunResponse])
def list_verification_runs(project_id: UUID, db: Session = Depends(get_db)) -> list[VerificationRun]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list(
        db.scalars(select(VerificationRun).where(VerificationRun.project_id == project_id).order_by(VerificationRun.created_at.desc())).all()
    )


@app.get("/projects/{project_id}/verification-runs/{run_id}", response_model=VerificationRunDetailResponse)
def get_verification_run(project_id: UUID, run_id: UUID, db: Session = Depends(get_db)) -> VerificationRunDetailResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    run = db.get(VerificationRun, run_id)
    if run is None or run.project_id != project.id:
        raise HTTPException(status_code=404, detail="Verification run not found")
    raw_output = json.loads(Path(run.raw_output_artifact_path).read_text(encoding="utf-8"))
    normalized_output = json.loads(Path(run.normalized_output_artifact_path).read_text(encoding="utf-8"))
    explanations: list[dict] = []
    if run.explanation_artifact_path:
        explanations = json.loads(Path(run.explanation_artifact_path).read_text(encoding="utf-8"))
    return VerificationRunDetailResponse(
        **VerificationRunResponse.model_validate(run, from_attributes=True).model_dump(),
        raw_output=raw_output,
        normalized_output=normalized_output,
        explanations=explanations,
    )
