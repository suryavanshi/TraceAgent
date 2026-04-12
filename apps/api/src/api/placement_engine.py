from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from design_ir.models import BoardIR, ComponentInstance, Constraint, PlacementDecision, SchematicIR

from api.placement_scoring import PLACEMENT_PRIORITIES, PlacementScorer


@dataclass(frozen=True)
class PlannedPlacement:
    footprint_id: str
    instance_id: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    priority_group: str
    score: float
    rationale: tuple[str, ...]
    anchors: tuple[str, ...]
    constraints_applied: tuple[str, ...]


class DeterministicPlacementEngine:
    def __init__(self, scorer: PlacementScorer | None = None) -> None:
        self.scorer = scorer or PlacementScorer()

    def place(self, board_ir: BoardIR, schematic_ir: SchematicIR) -> BoardIR:
        working = board_ir.model_copy(deep=True)
        planned = self._build_plan(working, schematic_ir)
        self._apply_plan(working, planned)
        self._add_visualization(working, planned)
        return working

    def _build_plan(self, board_ir: BoardIR, schematic_ir: SchematicIR) -> list[PlannedPlacement]:
        by_instance = {instance.instance_id: instance for instance in schematic_ir.component_instances}
        nets_by_instance = self._nets_by_instance(schematic_ir)
        board_w = board_ir.board_outline.dimensions_mm.get("width", 100.0)
        board_h = board_ir.board_outline.dimensions_mm.get("height", 80.0)
        margin = 5.0

        constraints_by_instance = self._constraints_by_instance(board_ir.placement_constraints)
        decisions: list[PlannedPlacement] = []
        placements_by_instance: dict[str, tuple[float, float]] = {}

        ordered = sorted(board_ir.footprints, key=lambda fp: fp.instance_id)
        for index, fp in enumerate(ordered):
            component = by_instance.get(fp.instance_id)
            if component is None:
                continue
            nets = nets_by_instance.get(fp.instance_id, set())
            is_decoupling = component.reference.upper().startswith("C") and any(
                token in " ".join(sorted(nets)) for token in ("VDD", "VCC", "VIN", "VBUS", "3V3", "5V")
            )
            is_switcher = any(token in fp.package.upper() for token in ("BUCK", "BOOST", "SW", "REG"))
            is_analog_sensitive = any(token in fp.package.upper() or token in component.symbol_id.upper() for token in ("ADC", "AFE", "SENSOR", "AMP"))

            score = self.scorer.score(
                component,
                fp,
                is_decoupling=is_decoupling,
                is_switcher=is_switcher,
                is_analog_sensitive=is_analog_sensitive,
            )

            lane = PLACEMENT_PRIORITIES.index(score.priority_group) if score.priority_group in PLACEMENT_PRIORITIES else len(PLACEMENT_PRIORITIES)
            base_x = margin + (lane % 3) * (board_w - (2 * margin)) / 3.0 + 8.0
            base_y = margin + (index // 3) * 10.0 + lane * 2.5
            x_mm = min(max(base_x, margin), board_w - margin)
            y_mm = min(max(base_y, margin), board_h - margin)
            rotation_deg = 0.0

            rationale = list(score.reasons)
            anchors: list[str] = []
            applied_constraints: list[str] = []

            if score.priority_group == "connectors_edge":
                x_mm, y_mm = margin + (len(decisions) * 12.0) % (board_w - 2 * margin), board_h - margin
                rationale.append("edge connector anchored on board edge")
            if score.priority_group == "clocks":
                mcu_anchor = self._find_first_group(decisions, "main_processor")
                if mcu_anchor:
                    x_mm = mcu_anchor[0] + 6.0
                    y_mm = mcu_anchor[1]
                    anchors.append("main_processor")
                    rationale.append("crystal loop shortened by MCU adjacency")
            if is_decoupling:
                mcu_anchor = self._find_first_group(decisions, "main_processor")
                if mcu_anchor:
                    x_mm = mcu_anchor[0] + 3.0
                    y_mm = mcu_anchor[1] + 3.0
                    anchors.append("main_processor")
                    rationale.append("decoupling moved near supply anchor")
            if is_switcher:
                pwr_anchor = self._find_first_group(decisions, "power_entry_protection")
                if pwr_anchor:
                    x_mm = pwr_anchor[0] + 6.0
                    y_mm = pwr_anchor[1] + 4.0
                    anchors.append("power_entry_protection")
                    rationale.append("switcher compact cluster near power entry")
            if is_analog_sensitive:
                x_mm = min(board_w - margin, x_mm + 12.0)
                y_mm = max(margin, board_h * 0.25)
                rationale.append("analog block displaced away from noisy power cluster")

            if score.priority_group == "power_entry_protection":
                conn_anchor = self._find_first_group(decisions, "connectors_edge")
                if conn_anchor:
                    x_mm = conn_anchor[0]
                    y_mm = max(margin, conn_anchor[1] - 7.0)
                    anchors.append("connectors_edge")
                    rationale.append("protection device adjacent to exposed connector")

            for constraint in constraints_by_instance.get(fp.instance_id, []):
                x_mm, y_mm, rotation_deg, note = self._apply_constraint(
                    constraint,
                    x_mm,
                    y_mm,
                    rotation_deg,
                    placements_by_instance,
                    board_w,
                    board_h,
                    margin,
                )
                if note:
                    applied_constraints.append(note)
                    rationale.append(note)

            x_mm = round(min(max(x_mm, margin), board_w - margin), 3)
            y_mm = round(min(max(y_mm, margin), board_h - margin), 3)
            placements_by_instance[fp.instance_id] = (x_mm, y_mm)

            decisions.append(
                PlannedPlacement(
                    footprint_id=fp.footprint_id,
                    instance_id=fp.instance_id,
                    x_mm=x_mm,
                    y_mm=y_mm,
                    rotation_deg=rotation_deg,
                    priority_group=score.priority_group,
                    score=round(score.score, 3),
                    rationale=tuple(rationale),
                    anchors=tuple(sorted(set(anchors))),
                    constraints_applied=tuple(applied_constraints),
                )
            )

        return sorted(
            decisions,
            key=lambda item: (
                PLACEMENT_PRIORITIES.index(item.priority_group) if item.priority_group in PLACEMENT_PRIORITIES else 999,
                -item.score,
                item.instance_id,
            ),
        )

    def _apply_plan(self, board_ir: BoardIR, planned: list[PlannedPlacement]) -> None:
        by_instance = {item.instance_id: item for item in planned}
        for footprint in board_ir.footprints:
            plan = by_instance.get(footprint.instance_id)
            if plan is None:
                continue
            footprint.placement = {"x_mm": plan.x_mm, "y_mm": plan.y_mm, "rotation_deg": plan.rotation_deg}

        board_ir.placement_decisions = [
            PlacementDecision(
                decision_id=f"place_{item.instance_id}",
                footprint_id=item.footprint_id,
                instance_id=item.instance_id,
                priority_group=item.priority_group,
                score=item.score,
                rationale=list(item.rationale),
                anchors=list(item.anchors),
                constraints_applied=list(item.constraints_applied),
            )
            for item in planned
        ]

    def _add_visualization(self, board_ir: BoardIR, planned: list[PlannedPlacement]) -> None:
        board_ir.placement_visualization = {
            "priority_order": list(PLACEMENT_PRIORITIES),
            "overlays": [
                {
                    "instance_id": item.instance_id,
                    "group": item.priority_group,
                    "x_mm": item.x_mm,
                    "y_mm": item.y_mm,
                    "score": item.score,
                    "labels": list(item.rationale[:3]),
                }
                for item in planned
            ],
        }

    def _constraints_by_instance(self, constraints: list[Constraint]) -> dict[str, list[Constraint]]:
        mapping: dict[str, list[Constraint]] = {}
        for constraint in constraints:
            fields = self._parse_expression(constraint.expression)
            instance_id = fields.get("instance_id")
            if instance_id:
                mapping.setdefault(instance_id, []).append(constraint)
        return mapping

    def _apply_constraint(
        self,
        constraint: Constraint,
        x_mm: float,
        y_mm: float,
        rotation_deg: float,
        placements_by_instance: dict[str, tuple[float, float]],
        board_w: float,
        board_h: float,
        margin: float,
    ) -> tuple[float, float, float, str | None]:
        fields = self._parse_expression(constraint.expression)

        if constraint.kind == "edge_locked":
            edge = fields.get("edge", "bottom")
            offset = float(fields.get("offset_mm", "0"))
            if edge == "top":
                return margin + offset, margin, rotation_deg, f"edge_locked({edge})"
            if edge == "bottom":
                return margin + offset, board_h - margin, rotation_deg, f"edge_locked({edge})"
            if edge == "left":
                return margin, margin + offset, rotation_deg, f"edge_locked({edge})"
            return board_w - margin, margin + offset, rotation_deg, f"edge_locked(right)"

        if constraint.kind == "region_preference":
            x_min = float(fields.get("x_min", margin))
            x_max = float(fields.get("x_max", board_w - margin))
            y_min = float(fields.get("y_min", margin))
            y_max = float(fields.get("y_max", board_h - margin))
            return min(max(x_mm, x_min), x_max), min(max(y_mm, y_min), y_max), rotation_deg, "region_preference"

        if constraint.kind == "near_component":
            anchor = fields.get("anchor_instance_id")
            distance = float(fields.get("distance_mm", "6"))
            if anchor and anchor in placements_by_instance:
                ax, ay = placements_by_instance[anchor]
                return ax + distance, ay, rotation_deg, f"near_component({anchor})"

        if constraint.kind == "distance_limit":
            anchor = fields.get("anchor_instance_id")
            max_distance = float(fields.get("max_distance_mm", "10"))
            if anchor and anchor in placements_by_instance:
                ax, ay = placements_by_instance[anchor]
                delta_x = x_mm - ax
                delta_y = y_mm - ay
                distance = hypot(delta_x, delta_y)
                if distance > max_distance and distance > 0:
                    scale = max_distance / distance
                    return ax + (delta_x * scale), ay + (delta_y * scale), rotation_deg, f"distance_limit({anchor})"

        if constraint.kind == "orientation_preference":
            preferred = float(fields.get("rotation_deg", "0"))
            return x_mm, y_mm, preferred, f"orientation_preference({preferred})"

        return x_mm, y_mm, rotation_deg, None

    def _parse_expression(self, expression: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for part in expression.split(";"):
            token = part.strip()
            if not token or "=" not in token:
                continue
            key, value = token.split("=", 1)
            fields[key.strip()] = value.strip()
        return fields

    def _find_first_group(self, decisions: list[PlannedPlacement], group: str) -> tuple[float, float] | None:
        for item in decisions:
            if item.priority_group == group:
                return item.x_mm, item.y_mm
        return None

    def _nets_by_instance(self, schematic_ir: SchematicIR) -> dict[str, set[str]]:
        nets_by_instance: dict[str, set[str]] = {}
        for net in schematic_ir.nets:
            net_name = (net.name or net.net_id).upper()
            for node in net.nodes:
                nets_by_instance.setdefault(node.instance_id, set()).add(net_name)
        return nets_by_instance
