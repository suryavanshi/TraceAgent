from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from design_ir.models import (
    BoardIR,
    CanonicalDesignBundle,
    CircuitSpec,
    ImpactDomain,
    PatchCategory,
    PatchImpactAnalysis,
    PatchOperation,
    PatchPlan,
    Footprint,
    Region,
    SchematicIR,
    Severity,
    VerificationReport,
)
from design_ir.patching import PatchApplicationError, PatchEngine, PatchSession


class VisualEdit(BaseModel):
    object_id: str = Field(min_length=1)
    kind: Literal["move_footprint", "rotate_footprint", "lock_footprint", "assign_region", "toggle_keepout"]
    x_mm: float | None = None
    y_mm: float | None = None
    delta_deg: float | None = None
    locked: bool | None = None
    region_id: str | None = None


@dataclass
class AppliedVisualEdit:
    patch_plan: PatchPlan
    board_ir: BoardIR
    summary: str
    object_id: str


class ObjectIdentity:
    FOOTPRINT_PREFIX = "footprint:"

    @classmethod
    def for_footprint(cls, footprint_id: str) -> str:
        return f"{cls.FOOTPRINT_PREFIX}{footprint_id}"

    @classmethod
    def footprint_id_from_object_id(cls, object_id: str) -> str:
        if not object_id.startswith(cls.FOOTPRINT_PREFIX):
            raise PatchApplicationError(f"Unsupported object id '{object_id}'")
        return object_id.removeprefix(cls.FOOTPRINT_PREFIX)


class VisualEditSyncService:
    def __init__(self) -> None:
        self._engine = PatchEngine()
        self._sessions: dict[str, PatchSession] = {}

    def ensure_session(self, project_id: str, board_ir: BoardIR) -> None:
        if project_id in self._sessions:
            return
        bundle = CanonicalDesignBundle(
            circuit_spec=CircuitSpec(product_name="visual-edit", summary="visual-edit", target_board_type="unknown"),
            schematic_ir=SchematicIR(),
            board_ir=board_ir,
            patch_plan=PatchPlan(
                user_intent="bootstrap visual edit session",
                affected_objects=[],
                operations=[],
                impact_scope="board",
                requires_confirmation=False,
                category=PatchCategory.MOVE_FOOTPRINT,
                impact_analysis=PatchImpactAnalysis(domain=ImpactDomain.BOARD_ONLY),
            ),
            verification_report=VerificationReport(tool="visual-edit", severity=Severity.INFO),
        )
        self._sessions[project_id] = PatchSession(current=bundle)

    def apply(self, project_id: str, edit: VisualEdit) -> AppliedVisualEdit:
        if project_id not in self._sessions:
            raise PatchApplicationError("Visual edit session is not initialized")
        plan = self._to_patch_plan(self._sessions[project_id].current.board_ir, edit)
        result = self._sessions[project_id].apply(self._engine, plan)
        return AppliedVisualEdit(
            patch_plan=plan,
            board_ir=result.updated_bundle.board_ir,
            summary=self._summarize(edit),
            object_id=edit.object_id,
        )

    def undo(self, project_id: str) -> BoardIR:
        if project_id not in self._sessions:
            raise PatchApplicationError("Visual edit session is not initialized")
        return self._sessions[project_id].undo().board_ir

    def _to_patch_plan(self, board_ir: BoardIR, edit: VisualEdit) -> PatchPlan:
        footprint_id = ObjectIdentity.footprint_id_from_object_id(edit.object_id)
        updated_footprints = [Footprint.model_validate(fp).model_copy(deep=True) for fp in board_ir.footprints]
        target = next((fp for fp in updated_footprints if fp.footprint_id == footprint_id), None)
        if target is None:
            raise PatchApplicationError(f"Unknown footprint '{footprint_id}'")

        if edit.kind == "move_footprint":
            if edit.x_mm is None or edit.y_mm is None:
                raise PatchApplicationError("move_footprint requires x_mm and y_mm")
            target.placement["x_mm"] = edit.x_mm
            target.placement["y_mm"] = edit.y_mm
            category = PatchCategory.MOVE_FOOTPRINT
        elif edit.kind == "rotate_footprint":
            if edit.delta_deg is None:
                raise PatchApplicationError("rotate_footprint requires delta_deg")
            current_rotation = target.placement.get("rotation_deg", 0.0)
            target.placement["rotation_deg"] = current_rotation + edit.delta_deg
            category = PatchCategory.ROTATE_FOOTPRINT
        elif edit.kind == "lock_footprint":
            if edit.locked is None:
                raise PatchApplicationError("lock_footprint requires locked")
            target.fixed = edit.locked
            category = PatchCategory.LOCK_FOOTPRINT
        elif edit.kind == "assign_region":
            if not edit.region_id:
                raise PatchApplicationError("assign_region requires region_id")
            target.placement["region_id"] = edit.region_id
            category = PatchCategory.ASSIGN_REGION
        else:
            keepouts = [item.model_copy(deep=True) for item in board_ir.keepouts]
            existing = next((item for item in keepouts if item.region_id == footprint_id), None)
            if existing:
                keepouts = [item for item in keepouts if item.region_id != footprint_id]
            else:
                keepouts.append(
                    Region(
                        region_id=footprint_id,
                        region_type="footprint_keepout",
                        layers=["F.Cu"],
                        geometry={"shape": "rect", "footprint_id": footprint_id},
                    )
                )
            return PatchPlan(
                user_intent=self._summarize(edit),
                affected_objects=[edit.object_id, "board_ir.keepouts"],
                operations=[PatchOperation(op="update", path="board_ir.keepouts", value=keepouts)],
                impact_scope="board",
                requires_confirmation=False,
                category=PatchCategory.TOGGLE_KEEPOUT,
                impact_analysis=PatchImpactAnalysis(domain=ImpactDomain.BOARD_ONLY, requires_reverification=True),
            )

        return PatchPlan(
            user_intent=self._summarize(edit),
            affected_objects=[edit.object_id],
            operations=[PatchOperation(op="update", path="board_ir.footprints", value=updated_footprints)],
            impact_scope="board",
            requires_confirmation=False,
            category=category,
            impact_analysis=PatchImpactAnalysis(domain=ImpactDomain.BOARD_ONLY, requires_rerouting=edit.kind == "move_footprint", requires_reverification=True),
        )

    def _summarize(self, edit: VisualEdit) -> str:
        if edit.kind == "move_footprint":
            return f"Moved {edit.object_id} to ({edit.x_mm:.2f} mm, {edit.y_mm:.2f} mm)."
        if edit.kind == "rotate_footprint":
            return f"Rotated {edit.object_id} by {edit.delta_deg:.1f}°."  # type: ignore[arg-type]
        if edit.kind == "lock_footprint":
            status = "locked" if edit.locked else "unlocked"
            return f"{status.capitalize()} {edit.object_id}."
        if edit.kind == "assign_region":
            return f"Assigned {edit.object_id} to region '{edit.region_id}'."
        return f"Toggled keepout for {edit.object_id}."
