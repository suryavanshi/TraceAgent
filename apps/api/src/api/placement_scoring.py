from __future__ import annotations

from dataclasses import dataclass

from design_ir.models import ComponentInstance, Footprint


PLACEMENT_PRIORITIES: tuple[str, ...] = (
    "connectors_edge",
    "mounting_holes",
    "power_entry_protection",
    "main_processor",
    "clocks",
    "regulators",
    "sensors_analog",
    "debug_headers",
    "passives_decoupling",
)


@dataclass(frozen=True)
class PlacementScore:
    priority_group: str
    score: float
    reasons: tuple[str, ...]


class PlacementScorer:
    """Scores footprints deterministically without mutating BoardIR state."""

    _priority_weight = {name: index for index, name in enumerate(PLACEMENT_PRIORITIES)}

    def classify(self, component: ComponentInstance, footprint: Footprint) -> str:
        reference = component.reference.upper()
        package = footprint.package.upper()
        symbol_hint = component.symbol_id.upper()

        if reference.startswith("J") or "CONN" in package or "USB" in package:
            return "connectors_edge"
        if reference.startswith("H") or "MOUNT" in package:
            return "mounting_holes"
        if any(token in package or token in symbol_hint for token in ("FUSE", "TVS", "ESD", "POWER_IN", "VBUS")):
            return "power_entry_protection"
        if reference.startswith("U") and any(token in package or token in symbol_hint for token in ("MCU", "MPU", "ESP", "STM32", "NRF")):
            return "main_processor"
        if reference.startswith("Y") or "XTAL" in package or "CRYSTAL" in package:
            return "clocks"
        if any(token in package or token in symbol_hint for token in ("BUCK", "BOOST", "LDO", "REG", "PMIC")):
            return "regulators"
        if reference.startswith("U") and any(token in package or token in symbol_hint for token in ("ADC", "AFE", "SENSOR", "AMP", "OPAMP")):
            return "sensors_analog"
        if reference.startswith("J") and ("SWD" in package or "JTAG" in package or "TAG" in symbol_hint):
            return "debug_headers"
        return "passives_decoupling"

    def score(
        self,
        component: ComponentInstance,
        footprint: Footprint,
        *,
        is_decoupling: bool,
        is_switcher: bool,
        is_analog_sensitive: bool,
    ) -> PlacementScore:
        priority_group = self.classify(component, footprint)
        base = 1000.0 - (self._priority_weight.get(priority_group, 99) * 100.0)
        reasons: list[str] = [f"priority group={priority_group}"]

        if is_decoupling:
            base += 25.0
            reasons.append("decoupling capacitor bias")
        if is_switcher:
            base += 20.0
            reasons.append("switcher compactness bias")
        if is_analog_sensitive:
            base += 15.0
            reasons.append("analog sensitivity isolation bias")

        package_len_bias = max(0.0, 10.0 - min(len(footprint.package), 10)) / 10.0
        base += package_len_bias
        reasons.append("deterministic package-length tie-break")

        return PlacementScore(priority_group=priority_group, score=base, reasons=tuple(reasons))
