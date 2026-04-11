from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from design_ir.models import (
    Annotation,
    CircuitSpec,
    ComponentInstance,
    Net,
    NetLabel,
    NetNode,
    Pin,
    PinDirection,
    SchematicIR,
    Symbol,
)


Provenance = Literal["llm", "rules", "user"]


class SynthesisObjectProvenance(BaseModel):
    object_type: str
    object_id: str
    provenance: Provenance


class PowerTreeEdge(BaseModel):
    source_net: str
    sink_net: str
    via_instance_id: str
    provenance: Provenance = "llm"


class DecouplingRecommendation(BaseModel):
    instance_id: str
    supply_net: str
    capacitor_instance_id: str
    recommendation: str
    provenance: Provenance = "rules"


class SchematicLintWarning(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error"] = "warning"


class SchematicSynthesisResult(BaseModel):
    schematic_ir: SchematicIR
    power_tree: list[PowerTreeEdge] = Field(default_factory=list)
    support_passives: list[str] = Field(default_factory=list)
    protection_circuitry: list[str] = Field(default_factory=list)
    programming_interfaces: list[str] = Field(default_factory=list)
    decoupling_recommendations: list[DecouplingRecommendation] = Field(default_factory=list)
    warnings: list[SchematicLintWarning] = Field(default_factory=list)
    provenance: list[SynthesisObjectProvenance] = Field(default_factory=list)


class SelectedPart(BaseModel):
    functional_role: str
    mpn: str
    symbol_id: str
    reference_prefix: str = "U"


class DraftSchematicPlan(BaseModel):
    symbols: list[Symbol] = Field(default_factory=list)
    component_instances: list[ComponentInstance] = Field(default_factory=list)
    pins: list[Pin] = Field(default_factory=list)
    nets: list[Net] = Field(default_factory=list)
    net_labels: list[NetLabel] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)
    power_tree: list[PowerTreeEdge] = Field(default_factory=list)
    support_passives: list[str] = Field(default_factory=list)
    protection_circuitry: list[str] = Field(default_factory=list)
    programming_interfaces: list[str] = Field(default_factory=list)


class RuleBasedSchematicPlanner:
    """Acts as the LLM planning stage while keeping deterministic testability."""

    def plan(self, circuit_spec: CircuitSpec, selected_parts: list[SelectedPart]) -> DraftSchematicPlan:
        symbols: list[Symbol] = []
        instances: list[ComponentInstance] = []
        pins: list[Pin] = []
        nets: list[Net] = []
        labels: list[NetLabel] = []
        power_tree: list[PowerTreeEdge] = []
        protection: list[str] = []
        programming: list[str] = []

        rails = circuit_spec.power_rails or []
        for rail_index, rail in enumerate(rails, start=1):
            net_id = f"net_power_{rail_index}"
            nets.append(Net(net_id=net_id, name=rail.name.upper().replace(" ", "_")))
            labels.append(NetLabel(net_id=net_id, label=rail.name.upper().replace(" ", "_")))

        has_i2c = any("i2c" in interface.name.lower() for interface in circuit_spec.interfaces)
        if has_i2c:
            nets.extend(
                [
                    Net(net_id="net_i2c_scl", name="I2C_SCL"),
                    Net(net_id="net_i2c_sda", name="I2C_SDA"),
                ]
            )
            labels.extend(
                [
                    NetLabel(net_id="net_i2c_scl", label="I2C_SCL"),
                    NetLabel(net_id="net_i2c_sda", label="I2C_SDA"),
                ]
            )

        for idx, part in enumerate(selected_parts, start=1):
            instance_id = f"inst_{idx}"
            symbol_id = part.symbol_id
            ref = f"{part.reference_prefix}{idx}"
            symbols.append(Symbol(symbol_id=symbol_id, kind=part.functional_role))
            instances.append(
                ComponentInstance(
                    instance_id=instance_id,
                    symbol_id=symbol_id,
                    reference=ref,
                    value=part.mpn,
                    properties={"functional_role": part.functional_role, "mpn": part.mpn},
                )
            )
            pins.extend(
                [
                    Pin(pin_id=f"{instance_id}_vcc", instance_id=instance_id, number="1", name="VCC", direction=PinDirection.POWER),
                    Pin(pin_id=f"{instance_id}_gnd", instance_id=instance_id, number="2", name="GND", direction=PinDirection.POWER),
                    Pin(pin_id=f"{instance_id}_en", instance_id=instance_id, number="3", name="EN", direction=PinDirection.INPUT),
                ]
            )

            if rails:
                nets[0].nodes.append(NetNode(instance_id=instance_id, pin_number="1"))
                if len(rails) > 1:
                    power_tree.append(PowerTreeEdge(source_net=rails[0].name.upper().replace(" ", "_"), sink_net=rails[1].name.upper().replace(" ", "_"), via_instance_id=instance_id))

            gnd_net = next((net for net in nets if net.name == "GND"), None)
            if gnd_net is None:
                nets.append(Net(net_id="net_gnd", name="GND", nodes=[NetNode(instance_id=instance_id, pin_number="2")]))
                labels.append(NetLabel(net_id="net_gnd", label="GND"))
            else:
                gnd_net.nodes.append(NetNode(instance_id=instance_id, pin_number="2"))

            role = part.functional_role.lower()
            if "connector" in role or "usb" in role:
                protection.append(instance_id)
            if "mcu" in role or "microcontroller" in role:
                programming.append(instance_id)
                if has_i2c:
                    for net_name in ("I2C_SCL", "I2C_SDA"):
                        net = next(net for net in nets if net.name == net_name)
                        net.nodes.append(NetNode(instance_id=instance_id, pin_number="4" if net_name.endswith("SCL") else "5"))

        return DraftSchematicPlan(
            symbols=symbols,
            component_instances=instances,
            pins=pins,
            nets=nets,
            net_labels=labels,
            power_tree=power_tree,
            protection_circuitry=protection,
            programming_interfaces=programming,
            annotations=[Annotation(annotation_id="a1", text="Generated by schematic synthesis planner", scope="global")],
        )


@dataclass
class DeterministicRuleEngine:
    pull_resistor_value: str = "10k"
    decoupling_value: str = "100nF"

    def enrich(self, plan: DraftSchematicPlan) -> SchematicSynthesisResult:
        symbols = list(plan.symbols)
        instances = list(plan.component_instances)
        pins = list(plan.pins)
        nets = [Net.model_validate(net.model_dump()) for net in plan.nets]
        labels = list(plan.net_labels)
        support_passives = list(plan.support_passives)
        decoupling: list[DecouplingRecommendation] = []
        provenance: list[SynthesisObjectProvenance] = []

        for symbol in symbols:
            provenance.append(SynthesisObjectProvenance(object_type="symbol", object_id=symbol.symbol_id, provenance="llm"))
        for instance in instances:
            provenance.append(
                SynthesisObjectProvenance(object_type="component_instance", object_id=instance.instance_id, provenance="llm")
            )

        # Deterministic pull-up / pull-down insertion for EN pins
        en_pins = [pin for pin in pins if pin.name.upper().startswith("EN")]
        for index, pin in enumerate(en_pins, start=1):
            resistor_id = f"inst_pullup_{index}"
            symbols.append(Symbol(symbol_id=f"sym_pullup_{index}", kind="resistor"))
            instances.append(
                ComponentInstance(
                    instance_id=resistor_id,
                    symbol_id=f"sym_pullup_{index}",
                    reference=f"RPU{index}",
                    value=self.pull_resistor_value,
                    properties={"purpose": "enable_pullup"},
                )
            )
            pins.extend(
                [
                    Pin(pin_id=f"{resistor_id}_1", instance_id=resistor_id, number="1", name="A", direction=PinDirection.PASSIVE),
                    Pin(pin_id=f"{resistor_id}_2", instance_id=resistor_id, number="2", name="B", direction=PinDirection.PASSIVE),
                ]
            )
            en_net_name = f"{pin.instance_id.upper()}_EN"
            en_net = next((net for net in nets if net.name == en_net_name), None)
            if en_net is None:
                en_net = Net(net_id=f"net_{en_net_name.lower()}", name=en_net_name, nodes=[])
                nets.append(en_net)
                labels.append(NetLabel(net_id=en_net.net_id, label=en_net_name))
            en_net.nodes.append(NetNode(instance_id=pin.instance_id, pin_number=pin.number))
            en_net.nodes.append(NetNode(instance_id=resistor_id, pin_number="1"))
            vcc_net = next((net for net in nets if net.name and net.name.startswith("VBUS")), None) or next(
                (net for net in nets if net.name and net.name not in {"GND", en_net_name}),
                None,
            )
            if vcc_net is not None:
                vcc_net.nodes.append(NetNode(instance_id=resistor_id, pin_number="2"))
            support_passives.append(resistor_id)
            provenance.append(SynthesisObjectProvenance(object_type="component_instance", object_id=resistor_id, provenance="rules"))

        # Deterministic decoupling insertion for IC VCC pins
        for index, pin in enumerate([pin for pin in pins if pin.name.upper() in {"VCC", "VDD", "VIN"}], start=1):
            cap_id = f"inst_decoup_{index}"
            cap_symbol_id = f"sym_decoup_{index}"
            symbols.append(Symbol(symbol_id=cap_symbol_id, kind="capacitor"))
            instances.append(
                ComponentInstance(
                    instance_id=cap_id,
                    symbol_id=cap_symbol_id,
                    reference=f"C{index}",
                    value=self.decoupling_value,
                    properties={"purpose": "decoupling"},
                )
            )
            pins.extend(
                [
                    Pin(pin_id=f"{cap_id}_1", instance_id=cap_id, number="1", name="A", direction=PinDirection.PASSIVE),
                    Pin(pin_id=f"{cap_id}_2", instance_id=cap_id, number="2", name="B", direction=PinDirection.PASSIVE),
                ]
            )
            target_net = next((net for net in nets if any(node.instance_id == pin.instance_id and node.pin_number == pin.number for node in net.nodes)), None)
            if target_net is None:
                target_net = Net(net_id=f"net_{pin.instance_id}_vcc", name=f"{pin.instance_id.upper()}_VCC", nodes=[])
                nets.append(target_net)
                labels.append(NetLabel(net_id=target_net.net_id, label=target_net.name or target_net.net_id))
            target_net.nodes.append(NetNode(instance_id=cap_id, pin_number="1"))
            gnd = next((net for net in nets if net.name == "GND"), None)
            if gnd is None:
                gnd = Net(net_id="net_gnd", name="GND", nodes=[])
                nets.append(gnd)
                labels.append(NetLabel(net_id="net_gnd", label="GND"))
            gnd.nodes.append(NetNode(instance_id=cap_id, pin_number="2"))
            decoupling.append(
                DecouplingRecommendation(
                    instance_id=pin.instance_id,
                    supply_net=target_net.name or target_net.net_id,
                    capacitor_instance_id=cap_id,
                    recommendation="Place capacitor close to IC supply pin",
                )
            )
            support_passives.append(cap_id)
            provenance.append(SynthesisObjectProvenance(object_type="component_instance", object_id=cap_id, provenance="rules"))

        # Net naming normalization
        for net in nets:
            net.name = self._normalize_net_name(net.name or net.net_id)

        schematic = SchematicIR(
            symbols=symbols,
            component_instances=instances,
            pins=pins,
            nets=nets,
            net_labels=[NetLabel(net_id=label.net_id, label=self._normalize_net_name(label.label)) for label in labels],
            annotations=plan.annotations,
        )

        result = SchematicSynthesisResult(
            schematic_ir=schematic,
            power_tree=plan.power_tree,
            support_passives=sorted(set(support_passives)),
            protection_circuitry=plan.protection_circuitry,
            programming_interfaces=plan.programming_interfaces,
            decoupling_recommendations=decoupling,
            provenance=provenance,
        )
        result.warnings = SchematicLintEngine().lint(result)
        return result

    @staticmethod
    def _normalize_net_name(name: str) -> str:
        return "_".join(name.strip().upper().replace("-", "_").split())


class SchematicLintEngine:
    def lint(self, result: SchematicSynthesisResult) -> list[SchematicLintWarning]:
        warnings: list[SchematicLintWarning] = []
        nets = result.schematic_ir.nets

        # missing decoupling
        supply_instances = {
            pin.instance_id
            for pin in result.schematic_ir.pins
            if pin.name.upper() in {"VCC", "VDD", "VIN"}
        }
        decoupled_instances = {rec.instance_id for rec in result.decoupling_recommendations}
        for instance_id in sorted(supply_instances - decoupled_instances):
            warnings.append(SchematicLintWarning(code="MISSING_DECOUPLING", message=f"Missing decoupling recommendation for {instance_id}"))

        # floating enable pins
        for pin in result.schematic_ir.pins:
            if not pin.name.upper().startswith("EN"):
                continue
            connected = any(node.instance_id == pin.instance_id and node.pin_number == pin.number for net in nets for node in net.nodes)
            if not connected:
                warnings.append(SchematicLintWarning(code="FLOATING_ENABLE", message=f"Enable pin {pin.pin_id} appears floating"))

        # missing I2C pull-ups
        i2c_net_names = {"I2C_SCL", "I2C_SDA"}
        existing_i2c = {net.name for net in nets if net.name in i2c_net_names}
        if existing_i2c:
            pullups = [
                comp for comp in result.schematic_ir.component_instances if comp.properties.get("purpose") == "enable_pullup"
            ]
            if len(pullups) < 2:
                warnings.append(SchematicLintWarning(code="MISSING_I2C_PULLUPS", message="I2C nets detected but pull-up count is insufficient"))

        # connector without protection
        connector_instances = [
            comp.instance_id
            for comp in result.schematic_ir.component_instances
            if "connector" in comp.properties.get("functional_role", "").lower() or "usb" in comp.properties.get("functional_role", "").lower()
        ]
        for instance_id in connector_instances:
            if instance_id not in result.protection_circuitry:
                warnings.append(SchematicLintWarning(code="CONNECTOR_WITHOUT_PROTECTION", message=f"Connector {instance_id} lacks protection circuitry"))

        # broken power tree
        if result.power_tree:
            known_nets = {net.name for net in nets}
            for edge in result.power_tree:
                if edge.source_net not in known_nets or edge.sink_net not in known_nets:
                    warnings.append(
                        SchematicLintWarning(
                            code="BROKEN_POWER_TREE",
                            message=f"Power edge {edge.source_net} -> {edge.sink_net} references missing net",
                            severity="error",
                        )
                    )
        else:
            warnings.append(SchematicLintWarning(code="BROKEN_POWER_TREE", message="No power tree edges were generated", severity="error"))

        return warnings


class SchematicSynthesisAgent:
    def __init__(self, planner: RuleBasedSchematicPlanner | None = None, rule_engine: DeterministicRuleEngine | None = None) -> None:
        self._planner = planner or RuleBasedSchematicPlanner()
        self._rule_engine = rule_engine or DeterministicRuleEngine()

    def synthesize(self, circuit_spec: CircuitSpec, selected_parts: list[SelectedPart]) -> SchematicSynthesisResult:
        plan = self._planner.plan(circuit_spec=circuit_spec, selected_parts=selected_parts)
        return self._rule_engine.enrich(plan)
