from __future__ import annotations

from dataclasses import dataclass

from design_ir.models import BoardIR, SchematicIR

from api.simulation import SimulationResult, SimulationService


@dataclass(frozen=True)
class ReviewFinding:
    category: str
    title: str
    advisory: str
    severity: str
    assumptions: list[str]
    facts: list[str]
    links: list[dict[str, str]]


class ReviewAgent:
    """Produces advisory design reviews from schematic + board context.

    Findings are explicitly non-signoff guidance and include links to affected
    objects for explainability.
    """

    def __init__(self, simulation_service: SimulationService | None = None) -> None:
        self._simulation_service = simulation_service or SimulationService()

    def review(self, schematic_ir: SchematicIR, board_ir: BoardIR) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        simulation_results = self._simulation_service.run(schematic_ir)
        findings.extend(self._power_tree_review(schematic_ir, simulation_results))
        findings.extend(self._protection_review(schematic_ir))
        findings.extend(self._grounding_review(schematic_ir))
        findings.extend(self._layout_risk_review(board_ir))
        return findings

    def _power_tree_review(self, schematic_ir: SchematicIR, simulations: list[SimulationResult]) -> list[ReviewFinding]:
        power_nets = [net for net in schematic_ir.nets if (net.name or "").upper().startswith(("V", "VBUS", "VIN", "3V", "5V"))]
        matched_simulation = next((result for result in simulations if result.analysis_type == "regulator_stages"), None)

        assumptions = ["Power topology is inferred from net naming and regulator-like reference designators."]
        facts = [f"Detected {len(power_nets)} named power-like net(s)."]
        links = [
            {"kind": "net", "id": net.name or net.net_id, "label": net.name or net.net_id}
            for net in power_nets[:4]
        ]
        if matched_simulation:
            assumptions.extend(matched_simulation.assumptions)
            facts.extend(matched_simulation.facts)
            links.extend({"kind": item.kind, "id": item.id, "label": item.label} for item in matched_simulation.links)

        return [
            ReviewFinding(
                category="power_tree_review",
                title="Power tree topology advisory",
                advisory="Ensure each regulator output rail has explicit load budgeting and headroom margins.",
                severity="medium",
                assumptions=assumptions,
                facts=facts,
                links=links,
            )
        ]

    def _protection_review(self, schematic_ir: SchematicIR) -> list[ReviewFinding]:
        likely_protection = [
            component
            for component in schematic_ir.component_instances
            if any(token in (component.value or "").lower() for token in ("tvs", "esd", "fuse"))
        ]

        severity = "low" if likely_protection else "high"
        advisory = (
            "Protection parts detected; verify they are placed at connector entry points."
            if likely_protection
            else "No obvious ESD/TVS/fuse protection detected. Add input and interface protection where appropriate."
        )

        return [
            ReviewFinding(
                category="protection_review",
                title="Protection circuitry advisory",
                advisory=advisory,
                severity=severity,
                assumptions=["Protection detection uses symbol values and may miss custom naming."],
                facts=[f"Detected {len(likely_protection)} probable protection component(s)."],
                links=[
                    {"kind": "component", "id": component.reference, "label": component.reference}
                    for component in likely_protection[:4]
                ],
            )
        ]

    def _grounding_review(self, schematic_ir: SchematicIR) -> list[ReviewFinding]:
        ground_nets = [net for net in schematic_ir.nets if (net.name or "").upper() in {"GND", "AGND", "PGND"}]
        return [
            ReviewFinding(
                category="grounding_review",
                title="Grounding strategy advisory",
                advisory="Validate return paths for high-current and sensitive analog nodes; avoid long shared returns.",
                severity="medium",
                assumptions=["Ground quality is estimated from net labels only; copper geometry is not simulated."],
                facts=[f"Detected {len(ground_nets)} explicit ground net label(s)."],
                links=[
                    {"kind": "net", "id": net.name or net.net_id, "label": net.name or net.net_id}
                    for net in ground_nets[:4]
                ],
            )
        ]

    def _layout_risk_review(self, board_ir: BoardIR) -> list[ReviewFinding]:
        unlocked_footprints = [item for item in board_ir.footprints if not item.fixed]
        keepout_count = len(board_ir.keepouts)
        severity = "medium" if unlocked_footprints else "low"

        return [
            ReviewFinding(
                category="layout_risk_review",
                title="Layout risk advisory",
                advisory="Review placement clusters, keepout strategy, and critical net routing escape paths before signoff.",
                severity=severity,
                assumptions=["Risk score is rule-based and does not replace PCB SI/PI analysis."],
                facts=[
                    f"Unlocked footprints: {len(unlocked_footprints)}.",
                    f"Keepout regions configured: {keepout_count}.",
                ],
                links=[
                    {"kind": "component", "id": item.footprint_id, "label": item.footprint_id}
                    for item in unlocked_footprints[:4]
                ],
            )
        ]
