from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA_VERSION = "1.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionedModel(StrictModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION

    @classmethod
    def validate_llm_payload(cls, payload: dict[str, Any]) -> "VersionedModel":
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"Invalid {cls.__name__} payload: {exc}") from exc


class NamedObject(StrictModel):
    name: str = Field(min_length=1)
    description: str | None = None


class CircuitSpec(VersionedModel):
    product_name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    target_board_type: str = Field(min_length=1)
    functional_blocks: list[NamedObject] = Field(default_factory=list)
    interfaces: list[NamedObject] = Field(default_factory=list)
    power_rails: list[NamedObject] = Field(default_factory=list)
    environmental_constraints: list[str] = Field(default_factory=list)
    mechanical_constraints: list[str] = Field(default_factory=list)
    cost_constraints: list[str] = Field(default_factory=list)
    manufacturing_constraints: list[str] = Field(default_factory=list)
    preferred_parts: list[str] = Field(default_factory=list)
    banned_parts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator(
        "environmental_constraints",
        "mechanical_constraints",
        "cost_constraints",
        "manufacturing_constraints",
        "preferred_parts",
        "banned_parts",
        "open_questions",
    )
    @classmethod
    def no_empty_items(cls, values: list[str]) -> list[str]:
        if any(not item.strip() for item in values):
            raise ValueError("List items must be non-empty strings")
        return values

    @model_validator(mode="after")
    def ensure_parts_not_conflicting(self) -> "CircuitSpec":
        overlap = sorted(set(self.preferred_parts).intersection(self.banned_parts))
        if overlap:
            raise ValueError(f"preferred_parts and banned_parts overlap: {overlap}")
        return self


class PinDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    PASSIVE = "passive"
    POWER = "power"


class Symbol(StrictModel):
    symbol_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    library_ref: str | None = None


class ComponentInstance(StrictModel):
    instance_id: str = Field(min_length=1)
    symbol_id: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    value: str | None = None
    properties: dict[str, str] = Field(default_factory=dict)


class Pin(StrictModel):
    pin_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    number: str = Field(min_length=1)
    name: str = Field(min_length=1)
    direction: PinDirection


class NetNode(StrictModel):
    instance_id: str = Field(min_length=1)
    pin_number: str = Field(min_length=1)


class Net(StrictModel):
    net_id: str = Field(min_length=1)
    name: str | None = None
    nodes: list[NetNode] = Field(default_factory=list)


class NetLabel(StrictModel):
    net_id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class HierarchicalSheet(StrictModel):
    sheet_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    parent_sheet_id: str | None = None


class Annotation(StrictModel):
    annotation_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    scope: str = Field(min_length=1)


class SchematicIR(VersionedModel):
    symbols: list[Symbol] = Field(default_factory=list)
    component_instances: list[ComponentInstance] = Field(default_factory=list)
    pins: list[Pin] = Field(default_factory=list)
    nets: list[Net] = Field(default_factory=list)
    net_labels: list[NetLabel] = Field(default_factory=list)
    hierarchical_sheets: list[HierarchicalSheet] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cross_refs(self) -> "SchematicIR":
        symbol_ids = {s.symbol_id for s in self.symbols}
        instance_ids = {c.instance_id for c in self.component_instances}
        net_ids = {n.net_id for n in self.nets}

        for component in self.component_instances:
            if component.symbol_id not in symbol_ids:
                raise ValueError(f"component {component.instance_id} references unknown symbol {component.symbol_id}")
        for pin in self.pins:
            if pin.instance_id not in instance_ids:
                raise ValueError(f"pin {pin.pin_id} references unknown instance {pin.instance_id}")
        for label in self.net_labels:
            if label.net_id not in net_ids:
                raise ValueError(f"net label {label.label} references unknown net {label.net_id}")
        return self


class BoardOutline(StrictModel):
    shape: str = Field(min_length=1)
    dimensions_mm: dict[str, float] = Field(default_factory=dict)


class StackupLayer(StrictModel):
    name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    thickness_um: float = Field(gt=0)


class Footprint(StrictModel):
    footprint_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    package: str = Field(min_length=1)
    library_ref: str | None = None
    placement: dict[str, float] = Field(default_factory=dict)
    fixed: bool = False
    provenance: str = Field(default="rules", min_length=1)


class MountingHole(StrictModel):
    hole_id: str = Field(min_length=1)
    diameter_mm: float = Field(gt=0)
    x_mm: float
    y_mm: float


class FixedEdgeConnector(StrictModel):
    connector_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    edge: Literal["top", "bottom", "left", "right"]
    offset_mm: float = Field(ge=0)


class Constraint(StrictModel):
    constraint_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    expression: str = Field(min_length=1)


class PlacementDecision(StrictModel):
    decision_id: str = Field(min_length=1)
    footprint_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    priority_group: str = Field(min_length=1)
    score: float
    rationale: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    constraints_applied: list[str] = Field(default_factory=list)


class NetClass(StrictModel):
    name: str = Field(min_length=1)
    nets: list[str] = Field(default_factory=list)
    rules: dict[str, float | int | str] = Field(default_factory=dict)


class Region(StrictModel):
    region_id: str = Field(min_length=1)
    region_type: str = Field(min_length=1)
    layers: list[str] = Field(default_factory=list)
    geometry: dict[str, float | str] = Field(default_factory=dict)


class RoutingIntent(StrictModel):
    net_or_group: str = Field(min_length=1)
    intent: str = Field(min_length=1)


class BoardIR(VersionedModel):
    board_outline: BoardOutline
    stackup: list[StackupLayer] = Field(default_factory=list)
    footprints: list[Footprint] = Field(default_factory=list)
    mounting_holes: list[MountingHole] = Field(default_factory=list)
    fixed_edge_connectors: list[FixedEdgeConnector] = Field(default_factory=list)
    placement_constraints: list[Constraint] = Field(default_factory=list)
    design_rules: list[Constraint] = Field(default_factory=list)
    net_classes: list[NetClass] = Field(default_factory=list)
    keepouts: list[Region] = Field(default_factory=list)
    zones: list[Region] = Field(default_factory=list)
    routing_intents: list[RoutingIntent] = Field(default_factory=list)
    placement_decisions: list[PlacementDecision] = Field(default_factory=list)
    placement_visualization: dict[str, Any] = Field(default_factory=dict)


class PatchOperation(StrictModel):
    op: Literal["add", "update", "remove", "move"]
    path: str = Field(min_length=1)
    value: Any | None = None


class PatchCategory(str, Enum):
    ADD_REMOVE_COMPONENT = "add_remove_component"
    SWAP_PART = "swap_part"
    RENAME_NET = "rename_net"
    CHANGE_POWER_RAIL_VALUE = "change_power_rail_value"
    MOVE_CONNECTOR = "move_connector"
    RESIZE_BOARD = "resize_board"
    WIDEN_TRACE_CLASS = "widen_trace_class"
    ADD_TEST_POINTS = "add_test_points"
    ADD_PROTECTION_CIRCUITRY = "add_protection_circuitry"


class ImpactDomain(str, Enum):
    SCHEMATIC_ONLY = "schematic_only"
    BOARD_ONLY = "board_only"
    BOTH = "both"


class PatchImpactAnalysis(StrictModel):
    domain: ImpactDomain
    requires_replacement: bool = False
    requires_rerouting: bool = False
    requires_reverification: bool = False


class UserChangeProvenance(StrictModel):
    source: Literal["user_instruction"] = "user_instruction"
    instruction: str = Field(min_length=1)
    actor: str = Field(default="user", min_length=1)


class PatchPlan(VersionedModel):
    user_intent: str = Field(min_length=1)
    affected_objects: list[str] = Field(default_factory=list)
    operations: list[PatchOperation] = Field(default_factory=list)
    impact_scope: Literal["local", "sheet", "board", "global"]
    requires_confirmation: bool
    category: PatchCategory = PatchCategory.ADD_REMOVE_COMPONENT
    impact_analysis: PatchImpactAnalysis = Field(
        default_factory=lambda: PatchImpactAnalysis(domain=ImpactDomain.SCHEMATIC_ONLY)
    )
    provenance: list[UserChangeProvenance] = Field(default_factory=list)


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Finding(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)


class VerificationReport(VersionedModel):
    tool: str = Field(min_length=1)
    severity: Severity
    findings: list[Finding] = Field(default_factory=list)
    affected_objects: list[str] = Field(default_factory=list)
    suggested_fixes: list[str] = Field(default_factory=list)


class CanonicalDesignBundle(VersionedModel):
    circuit_spec: CircuitSpec
    schematic_ir: SchematicIR
    board_ir: BoardIR
    patch_plan: PatchPlan
    verification_report: VerificationReport


class DesignIR(VersionedModel):
    design_id: str
    revision: int = Field(ge=0)
    nets: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
