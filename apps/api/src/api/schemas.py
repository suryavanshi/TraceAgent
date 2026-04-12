from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from design_ir.models import BoardIR, CircuitSpec, SchematicIR


class ProjectCreate(BaseModel):
    owner_email: str
    owner_display_name: str | None = None
    name: str
    description: str | None = None


class ProjectResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    artifact_root_dir: str
    snapshot_repo_dir: str
    created_at: datetime


class SnapshotFile(BaseModel):
    path: str = Field(min_length=1)
    content: str


class SnapshotCreate(BaseModel):
    title: str
    notes: str | None = None
    files: list[SnapshotFile] = Field(default_factory=list)


class SnapshotResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    notes: str | None
    artifact_dir: str
    git_commit_hash: str
    created_at: datetime


class SnapshotRevertResponse(BaseModel):
    project_id: UUID
    reverted_to_snapshot_id: UUID
    git_commit_hash: str


class RequirementsChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1)


class RequirementsDeriveRequest(BaseModel):
    latest_user_request: str = Field(min_length=1)
    chat_history: list[RequirementsChatMessage] = Field(default_factory=list)


class RequirementsDeriveResponse(BaseModel):
    proposed_circuit_spec: dict
    summary: str
    open_questions: list[str] = Field(default_factory=list)


class PartConstraintPayload(BaseModel):
    package: str | None = None
    min_voltage_v: float | None = None
    max_voltage_v: float | None = None
    min_current_a: float | None = None
    interface: str | None = None


class PartReviewRequest(BaseModel):
    circuit_spec: CircuitSpec
    constraints_by_role: dict[str, PartConstraintPayload] = Field(default_factory=dict)


class PartReviewCandidate(BaseModel):
    mpn: str
    functional_role: str
    confidence: float
    rationale: list[str] = Field(default_factory=list)
    symbol_ref: dict[str, str]
    footprint_ref: dict[str, str]
    package: str


class PartReviewBlock(BaseModel):
    functional_block: str
    candidates: list[PartReviewCandidate] = Field(default_factory=list)


class PartReviewResponse(BaseModel):
    block_reviews: list[PartReviewBlock] = Field(default_factory=list)


class SchematicSelectedPart(BaseModel):
    functional_role: str
    mpn: str
    symbol_id: str
    reference_prefix: str = "U"


class SchematicSynthesisRequest(BaseModel):
    circuit_spec: CircuitSpec
    selected_parts: list[SchematicSelectedPart] = Field(default_factory=list)


class SchematicLintWarningPayload(BaseModel):
    code: str
    message: str
    severity: str


class SchematicSynthesisResponse(BaseModel):
    schematic_ir: SchematicIR
    board_ir: BoardIR
    power_tree: list[dict[str, str]] = Field(default_factory=list)
    support_passives: list[str] = Field(default_factory=list)
    protection_circuitry: list[str] = Field(default_factory=list)
    programming_interfaces: list[str] = Field(default_factory=list)
    decoupling_recommendations: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[SchematicLintWarningPayload] = Field(default_factory=list)
    provenance: list[dict[str, str]] = Field(default_factory=list)
    saved_path: str
    kicad_project_path: str
    kicad_schematic_path: str
    kicad_sym_lib_table_path: str
    schematic_svg_path: str
    schematic_pdf_path: str
    schematic_svg: str
    board_ir_path: str
    kicad_pcb_path: str
    board_metadata: dict[str, str | int | float]


class VerificationRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    snapshot_id: UUID | None
    status: str
    report_artifact_path: str
    raw_output_artifact_path: str
    normalized_output_artifact_path: str
    explanation_artifact_path: str | None
    created_at: datetime


class VerificationRunDetailResponse(VerificationRunResponse):
    raw_output: dict
    normalized_output: dict
    explanations: list[dict]
