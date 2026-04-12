from __future__ import annotations

from dataclasses import dataclass, field

from design_ir.models import (
    BoardIR,
    BoardOutline,
    CircuitSpec,
    Constraint,
    FixedEdgeConnector,
    Footprint,
    MountingHole,
    NetClass,
    Region,
    RoutingIntent,
    SchematicIR,
    StackupLayer,
)

from api.placement_engine import DeterministicPlacementEngine


@dataclass
class BoardRulesBuilder:
    """Derives initial board rule scaffolding from CircuitSpec and SchematicIR."""

    def build(self, circuit_spec: CircuitSpec, schematic_ir: SchematicIR) -> tuple[list[NetClass], list[Constraint], list[Region]]:
        high_current_nets = [
            (net.name or net.net_id)
            for net in schematic_ir.nets
            if any(token in (net.name or "").upper() for token in ("VBUS", "VIN", "BAT", "MOTOR", "12V", "24V"))
        ]
        differential_nets = [
            (net.name or net.net_id)
            for net in schematic_ir.nets
            if any(token in (net.name or "").upper() for token in ("USB_D", "ETH", "CAN", "DP", "DN"))
        ]

        net_classes = [
            NetClass(
                name="Default",
                nets=sorted({net.name or net.net_id for net in schematic_ir.nets} - set(high_current_nets) - set(differential_nets)),
                rules={
                    "trace_width_mm": 0.20,
                    "clearance_mm": 0.20,
                    "via_drill_mm": 0.30,
                    "via_diameter_mm": 0.60,
                    "zone_clearance_mm": 0.25,
                    "zone_min_width_mm": 0.20,
                },
            )
        ]
        if high_current_nets:
            net_classes.append(
                NetClass(
                    name="Power",
                    nets=sorted(high_current_nets),
                    rules={
                        "trace_width_mm": 0.50,
                        "clearance_mm": 0.25,
                        "via_drill_mm": 0.40,
                        "via_diameter_mm": 0.80,
                        "zone_clearance_mm": 0.25,
                    },
                )
            )
        if differential_nets:
            net_classes.append(
                NetClass(
                    name="HighSpeed",
                    nets=sorted(differential_nets),
                    rules={
                        "trace_width_mm": 0.15,
                        "clearance_mm": 0.15,
                        "diff_pair_gap_mm": 0.15,
                        "via_drill_mm": 0.25,
                        "via_diameter_mm": 0.55,
                        "zone_clearance_mm": 0.20,
                    },
                )
            )

        design_rules = [
            Constraint(constraint_id="rule_min_trace", kind="trace_width", expression="trace_width_mm >= 0.15"),
            Constraint(constraint_id="rule_min_clearance", kind="clearance", expression="clearance_mm >= 0.15"),
            Constraint(constraint_id="rule_via", kind="via", expression="via_drill_mm >= 0.25 and via_diameter_mm >= 0.55"),
            Constraint(constraint_id="rule_zone", kind="zone", expression="zone_clearance_mm >= 0.20"),
        ]

        default_zones = [
            Region(
                region_id="zone_gnd_default",
                region_type="copper_zone",
                layers=["F.Cu", "B.Cu"],
                geometry={"net": "GND", "priority": 1, "fill_style": "solid"},
            )
        ]
        return net_classes, design_rules, default_zones


@dataclass
class BoardIRGenerator:
    rules_builder: BoardRulesBuilder = field(default_factory=BoardRulesBuilder)
    placement_engine: DeterministicPlacementEngine = field(default_factory=DeterministicPlacementEngine)

    def generate(self, circuit_spec: CircuitSpec, schematic_ir: SchematicIR) -> BoardIR:
        width_mm = self._extract_dimension(circuit_spec.mechanical_constraints, "width", 100.0)
        height_mm = self._extract_dimension(circuit_spec.mechanical_constraints, "height", 80.0)
        shape = "rectangle"
        if any("circular" in item.lower() or "round" in item.lower() for item in circuit_spec.mechanical_constraints):
            shape = "circle"

        stackup = [
            StackupLayer(name="F.Cu", kind="copper", thickness_um=35),
            StackupLayer(name="Core", kind="dielectric", thickness_um=1000),
            StackupLayer(name="B.Cu", kind="copper", thickness_um=35),
        ]

        footprints = [self._to_footprint(component) for component in schematic_ir.component_instances]
        mounting_holes = self._default_mounting_holes(width_mm, height_mm)
        fixed_connectors = self._edge_connectors(footprints)
        keepouts = [
            Region(
                region_id="edge_keepout",
                region_type="edge_clearance",
                layers=["F.Cu", "B.Cu"],
                geometry={"offset_mm": 0.5},
            )
        ]

        net_classes, design_rules, zones = self.rules_builder.build(circuit_spec, schematic_ir)

        board_ir = BoardIR(
            board_outline=BoardOutline(shape=shape, dimensions_mm={"width": width_mm, "height": height_mm}),
            stackup=stackup,
            footprints=footprints,
            mounting_holes=mounting_holes,
            fixed_edge_connectors=fixed_connectors,
            placement_constraints=self._default_placement_constraints(fixed_connectors),
            design_rules=design_rules,
            net_classes=net_classes,
            keepouts=keepouts,
            zones=zones,
            routing_intents=[RoutingIntent(net_or_group="*", intent="unrouted_template")],
        )
        return self.placement_engine.place(board_ir=board_ir, schematic_ir=schematic_ir)

    def _to_footprint(self, component) -> Footprint:
        package = component.properties.get("package") or component.properties.get("footprint") or "GENERIC_SMD"
        library = component.properties.get("footprint_library") or "TraceAgent"
        return Footprint(
            footprint_id=f"fp_{component.instance_id}",
            instance_id=component.instance_id,
            package=package,
            library_ref=f"{library}:{package}",
            placement={"x_mm": 20.0, "y_mm": 20.0, "rotation_deg": 0.0},
            fixed=False,
            provenance="schematic_instance",
        )

    def _default_mounting_holes(self, width_mm: float, height_mm: float) -> list[MountingHole]:
        margin = 3.0
        return [
            MountingHole(hole_id="mh_1", diameter_mm=3.2, x_mm=margin, y_mm=margin),
            MountingHole(hole_id="mh_2", diameter_mm=3.2, x_mm=width_mm - margin, y_mm=margin),
            MountingHole(hole_id="mh_3", diameter_mm=3.2, x_mm=width_mm - margin, y_mm=height_mm - margin),
            MountingHole(hole_id="mh_4", diameter_mm=3.2, x_mm=margin, y_mm=height_mm - margin),
        ]

    def _edge_connectors(self, footprints: list[Footprint]) -> list[FixedEdgeConnector]:
        connectors: list[FixedEdgeConnector] = []
        for footprint in footprints:
            package = footprint.package.lower()
            if "usb" in package or package.startswith("conn") or "header" in package:
                connectors.append(
                    FixedEdgeConnector(
                        connector_id=f"edge_{footprint.instance_id}",
                        instance_id=footprint.instance_id,
                        edge="bottom",
                        offset_mm=10.0 + len(connectors) * 8.0,
                    )
                )
        return connectors

    def _default_placement_constraints(self, connectors: list[FixedEdgeConnector]) -> list[Constraint]:
        constraints: list[Constraint] = []
        for connector in connectors:
            constraints.append(
                Constraint(
                    constraint_id=f"place_{connector.instance_id}_edge",
                    kind="edge_locked",
                    expression=f"instance_id={connector.instance_id};edge={connector.edge};offset_mm={connector.offset_mm}",
                )
            )
        return constraints

    def _extract_dimension(self, constraints: list[str], dim_name: str, default: float) -> float:
        for item in constraints:
            lower = item.lower()
            if dim_name in lower and "mm" in lower:
                digits = "".join(ch if (ch.isdigit() or ch == ".") else " " for ch in lower)
                tokens = [token for token in digits.split() if token]
                if tokens:
                    return float(tokens[0])
        return default
