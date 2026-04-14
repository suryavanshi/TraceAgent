from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from design_ir.models import SchematicIR


@dataclass(frozen=True)
class SimulationLink:
    kind: str
    id: str
    label: str


@dataclass(frozen=True)
class SimulationResult:
    analysis_type: str
    summary: str
    assumptions: list[str]
    facts: list[str]
    links: list[SimulationLink]


class SimulationService:
    """Lightweight schematic-level simulation abstraction for advisory analysis.

    This service is intentionally isolated from compile/verification flows and only
    provides quick estimates for circuits that are realistic to evaluate with simple
    heuristics in v1.
    """

    SUPPORTED_ANALYSES = ("regulator_stages", "filters", "op_amp_circuits")

    def run(self, schematic_ir: SchematicIR) -> list[SimulationResult]:
        results: list[SimulationResult] = []
        results.extend(self._simulate_regulator_stages(schematic_ir))
        results.extend(self._simulate_filters(schematic_ir))
        results.extend(self._simulate_op_amp_circuits(schematic_ir))
        return results

    def _simulate_regulator_stages(self, schematic_ir: SchematicIR) -> list[SimulationResult]:
        regulator_instances = [
            component
            for component in schematic_ir.component_instances
            if "reg" in component.reference.lower() or "ldo" in (component.value or "").lower()
        ]
        if not regulator_instances:
            return []

        net_names = [net.name or net.net_id for net in schematic_ir.nets]
        vout_nets = [name for name in net_names if "3v3" in name.lower() or "vout" in name.lower()]
        vin_nets = [name for name in net_names if "vin" in name.lower() or "vbus" in name.lower() or "5v" in name.lower()]

        assumptions = [
            "Estimated load current assumes nominal digital + analog mixed load profile.",
            "Dropout headroom estimate uses static VIN/VOUT naming heuristics, not SPICE models.",
        ]
        facts = [
            f"Detected {len(regulator_instances)} regulator-like stage(s) from symbol references.",
            f"Detected candidate input rails: {', '.join(vin_nets[:3]) if vin_nets else 'none'}.",
            f"Detected candidate output rails: {', '.join(vout_nets[:3]) if vout_nets else 'none'}.",
        ]

        links = [
            SimulationLink(kind="component", id=item.reference, label=item.reference)
            for item in regulator_instances[:4]
        ]
        links.extend(SimulationLink(kind="net", id=net, label=net) for net in (vin_nets + vout_nets)[:4])

        return [
            SimulationResult(
                analysis_type="regulator_stages",
                summary="Regulator stage simulation completed with schematic-level assumptions.",
                assumptions=assumptions,
                facts=facts,
                links=links,
            )
        ]

    def _simulate_filters(self, schematic_ir: SchematicIR) -> list[SimulationResult]:
        capacitor_instances = [component for component in schematic_ir.component_instances if component.reference.upper().startswith("C")]
        resistor_instances = [component for component in schematic_ir.component_instances if component.reference.upper().startswith("R")]
        if len(capacitor_instances) < 1 or len(resistor_instances) < 1:
            return []

        passive_counts = [len(capacitor_instances), len(resistor_instances)]
        average_passive_population = mean(passive_counts)

        links = [
            SimulationLink(kind="component", id=item.reference, label=item.reference)
            for item in (capacitor_instances[:2] + resistor_instances[:2])
        ]

        return [
            SimulationResult(
                analysis_type="filters",
                summary="Filter response estimated from RC population and common net naming patterns.",
                assumptions=[
                    "Cutoff estimations assume first-order RC behavior and nominal component values.",
                ],
                facts=[
                    f"Detected {len(capacitor_instances)} capacitors and {len(resistor_instances)} resistors.",
                    f"Average passive population indicator: {average_passive_population:.1f}.",
                ],
                links=links,
            )
        ]

    def _simulate_op_amp_circuits(self, schematic_ir: SchematicIR) -> list[SimulationResult]:
        opamp_instances = [
            component
            for component in schematic_ir.component_instances
            if "opamp" in (component.value or "").lower() or "op" in component.reference.lower()
        ]
        if not opamp_instances:
            return []

        links = [SimulationLink(kind="component", id=item.reference, label=item.reference) for item in opamp_instances[:3]]

        return [
            SimulationResult(
                analysis_type="op_amp_circuits",
                summary="Op-amp operating envelope estimated from topology hints.",
                assumptions=[
                    "Gain/bandwidth checks are inferred from symbol/value hints; transistor-level effects are not modeled.",
                ],
                facts=[f"Detected {len(opamp_instances)} op-amp-like component(s)."],
                links=links,
            )
        ]
