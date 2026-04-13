from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import (
    BoardIR,
    CanonicalDesignBundle,
    ComponentInstance,
    FixedEdgeConnector,
    Finding,
    Footprint,
    ImpactDomain,
    Net,
    NetClass,
    NetLabel,
    PatchCategory,
    PatchImpactAnalysis,
    PatchOperation,
    PatchPlan,
    SchematicIR,
    Severity,
    UserChangeProvenance,
    VerificationReport,
)


class PatchApplicationError(ValueError):
    pass


class PatchAgent:
    """Keyword-driven planner for converting user instructions into PatchPlan."""

    def plan_patch(self, instruction: str) -> PatchPlan:
        normalized = instruction.lower()
        category, operation = self._infer_category_and_operation(normalized)
        impact = self._infer_impact(category)

        return PatchPlan(
            user_intent=instruction,
            affected_objects=[operation.path],
            operations=[operation],
            impact_scope=self._impact_scope_for_domain(impact.domain),
            requires_confirmation=impact.requires_reverification,
            category=category,
            impact_analysis=impact,
            provenance=[UserChangeProvenance(instruction=instruction)],
        )

    def _infer_category_and_operation(self, instruction: str) -> tuple[PatchCategory, PatchOperation]:
        if "swap" in instruction:
            return PatchCategory.SWAP_PART, PatchOperation(op="update", path="schematic_ir.component_instances")
        if "rename net" in instruction:
            return PatchCategory.RENAME_NET, PatchOperation(op="update", path="schematic_ir.nets")
        if "power rail" in instruction or "3v3" in instruction or "5v" in instruction:
            return PatchCategory.CHANGE_POWER_RAIL_VALUE, PatchOperation(op="update", path="schematic_ir.net_labels")
        if "move connector" in instruction:
            return PatchCategory.MOVE_CONNECTOR, PatchOperation(op="move", path="board_ir.fixed_edge_connectors")
        if "resize board" in instruction or "board" in instruction and "resize" in instruction:
            return PatchCategory.RESIZE_BOARD, PatchOperation(op="update", path="board_ir.board_outline")
        if "widen trace" in instruction:
            return PatchCategory.WIDEN_TRACE_CLASS, PatchOperation(op="update", path="board_ir.net_classes")
        if "test point" in instruction:
            return PatchCategory.ADD_TEST_POINTS, PatchOperation(op="add", path="board_ir.footprints")
        if "protection" in instruction:
            return PatchCategory.ADD_PROTECTION_CIRCUITRY, PatchOperation(op="add", path="schematic_ir.component_instances")
        if "remove" in instruction:
            return PatchCategory.ADD_REMOVE_COMPONENT, PatchOperation(op="remove", path="schematic_ir.component_instances")
        return PatchCategory.ADD_REMOVE_COMPONENT, PatchOperation(op="add", path="schematic_ir.component_instances")

    def _infer_impact(self, category: PatchCategory) -> PatchImpactAnalysis:
        if category in {
            PatchCategory.SWAP_PART,
            PatchCategory.MOVE_CONNECTOR,
            PatchCategory.RESIZE_BOARD,
            PatchCategory.WIDEN_TRACE_CLASS,
            PatchCategory.ADD_TEST_POINTS,
        }:
            return PatchImpactAnalysis(
                domain=ImpactDomain.BOTH,
                requires_replacement=category in {PatchCategory.MOVE_CONNECTOR, PatchCategory.RESIZE_BOARD},
                requires_rerouting=category
                in {PatchCategory.MOVE_CONNECTOR, PatchCategory.RESIZE_BOARD, PatchCategory.WIDEN_TRACE_CLASS},
                requires_reverification=True,
            )
        if category in {PatchCategory.RENAME_NET, PatchCategory.CHANGE_POWER_RAIL_VALUE, PatchCategory.ADD_PROTECTION_CIRCUITRY}:
            return PatchImpactAnalysis(domain=ImpactDomain.SCHEMATIC_ONLY, requires_reverification=True)
        return PatchImpactAnalysis(domain=ImpactDomain.SCHEMATIC_ONLY, requires_reverification=False)

    @staticmethod
    def _impact_scope_for_domain(domain: ImpactDomain) -> str:
        if domain is ImpactDomain.BOTH:
            return "global"
        if domain is ImpactDomain.BOARD_ONLY:
            return "board"
        return "sheet"


@dataclass
class PatchDiff:
    machine_readable: dict[str, Any]
    user_summary: str


@dataclass
class PatchApplicationResult:
    updated_bundle: CanonicalDesignBundle
    recompiled_artifacts: list[str]
    diff: PatchDiff


class PatchEngine:
    def apply(self, bundle: CanonicalDesignBundle, plan: PatchPlan) -> PatchApplicationResult:
        original = bundle.model_copy(deep=True)
        mutated = bundle.model_copy(deep=True)
        try:
            self._apply_to_ir(mutated.schematic_ir, mutated.board_ir, plan)
            self._invalidate_verification_if_needed(mutated, plan)
            recompiled = self._recompile(mutated.schematic_ir, mutated.board_ir, plan.impact_analysis.domain)
            diff = self._build_diff(original, mutated, plan)
            return PatchApplicationResult(updated_bundle=mutated, recompiled_artifacts=recompiled, diff=diff)
        except Exception as exc:  # transactional rollback via no-mutate contract
            raise PatchApplicationError(f"Failed to apply patch transactionally: {exc}") from exc

    def _apply_to_ir(self, schematic: SchematicIR, board: BoardIR, plan: PatchPlan) -> None:
        for operation in plan.operations:
            target, field_name = self._resolve_target(schematic, board, operation.path)
            current = getattr(target, field_name)
            if operation.op == "add":
                if not isinstance(current, list):
                    raise PatchApplicationError(f"Cannot add to non-list field: {operation.path}")
                current.append(self._coerce_add_value(operation.path, operation.value, plan.user_intent))
            elif operation.op == "remove":
                if not isinstance(current, list) or not current:
                    raise PatchApplicationError(f"Cannot remove from empty/non-list field: {operation.path}")
                current.pop()
            elif operation.op in {"update", "move"}:
                setattr(target, field_name, operation.value if operation.value is not None else current)
            else:
                raise PatchApplicationError(f"Unsupported operation: {operation.op}")

    def _resolve_target(self, schematic: SchematicIR, board: BoardIR, path: str) -> tuple[Any, str]:
        segments = path.split(".")
        if len(segments) < 2:
            raise PatchApplicationError(f"Invalid path: {path}")
        root = segments[0]
        if root == "schematic_ir":
            target: Any = schematic
        elif root == "board_ir":
            target = board
        else:
            raise PatchApplicationError(f"Unknown path root: {root}")
        for segment in segments[1:-1]:
            target = getattr(target, segment)
        return target, segments[-1]

    def _coerce_add_value(self, path: str, value: Any, intent: str) -> Any:
        if path == "schematic_ir.component_instances":
            payload = value or {
                "instance_id": f"inst_{abs(hash(intent)) % 10000}",
                "symbol_id": "sym_patch",
                "reference": "U99",
                "value": intent,
                "properties": {},
            }
            return ComponentInstance.model_validate(payload)
        if path == "schematic_ir.nets":
            return Net.model_validate(value or {"net_id": "net_patch", "name": intent, "nodes": []})
        if path == "schematic_ir.net_labels":
            return NetLabel.model_validate(value or {"net_id": "net_patch", "label": intent})
        if path == "board_ir.footprints":
            payload = value or {
                "footprint_id": f"fp_{abs(hash(intent)) % 10000}",
                "instance_id": "inst_patch",
                "package": "TP",
                "placement": {},
                "fixed": False,
                "provenance": "user_patch",
            }
            return Footprint.model_validate(payload)
        if path == "board_ir.fixed_edge_connectors":
            return FixedEdgeConnector.model_validate(
                value
                or {
                    "connector_id": "conn_patch",
                    "instance_id": "inst_conn_patch",
                    "edge": "right",
                    "offset_mm": 1.0,
                }
            )
        if path == "board_ir.net_classes":
            return NetClass.model_validate(value or {"name": "patch", "nets": [], "rules": {}})
        return value

    def _invalidate_verification_if_needed(self, bundle: CanonicalDesignBundle, plan: PatchPlan) -> None:
        if not plan.impact_analysis.requires_reverification:
            return
        findings = list(bundle.verification_report.findings)
        findings.append(
            Finding(
                code="PATCH_REVERIFY_REQUIRED",
                message="Patch impact requires verification rerun before sign-off",
                details={"category": plan.category.value},
            )
        )
        bundle.verification_report = VerificationReport(
            tool="patch-engine",
            severity=Severity.CRITICAL,
            findings=findings,
            affected_objects=sorted(set(bundle.verification_report.affected_objects + plan.affected_objects)),
            suggested_fixes=["Rerun verification suite after patch application."],
        )

    def _recompile(self, schematic: SchematicIR, board: BoardIR, domain: ImpactDomain) -> list[str]:
        if domain == ImpactDomain.SCHEMATIC_ONLY:
            return ["schematic"]
        if domain == ImpactDomain.BOARD_ONLY:
            return ["board"]
        return ["schematic", "board"]

    def _build_diff(self, original: CanonicalDesignBundle, mutated: CanonicalDesignBundle, plan: PatchPlan) -> PatchDiff:
        before = original.model_dump(mode="json")
        after = mutated.model_dump(mode="json")
        changed_top_level = [key for key in after if after.get(key) != before.get(key)]
        machine = {
            "changed_keys": changed_top_level,
            "operations": [op.model_dump(mode="json") for op in plan.operations],
            "category": plan.category.value,
        }
        summary = f"Applied {plan.category.value} affecting {', '.join(changed_top_level) or 'no top-level fields'}."
        return PatchDiff(machine_readable=machine, user_summary=summary)


@dataclass
class PatchSession:
    current: CanonicalDesignBundle
    _undo: list[CanonicalDesignBundle] = field(default_factory=list)
    _redo: list[CanonicalDesignBundle] = field(default_factory=list)

    def apply(self, engine: PatchEngine, plan: PatchPlan) -> PatchApplicationResult:
        self._undo.append(self.current.model_copy(deep=True))
        result = engine.apply(self.current, plan)
        self.current = result.updated_bundle
        self._redo.clear()
        return result

    def undo(self) -> CanonicalDesignBundle:
        if not self._undo:
            raise PatchApplicationError("No undo snapshot available")
        self._redo.append(self.current.model_copy(deep=True))
        self.current = self._undo.pop()
        return self.current

    def redo(self) -> CanonicalDesignBundle:
        if not self._redo:
            raise PatchApplicationError("No redo snapshot available")
        self._undo.append(self.current.model_copy(deep=True))
        self.current = self._redo.pop()
        return self.current
