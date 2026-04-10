from __future__ import annotations

from dataclasses import dataclass

from design_ir.models import CircuitSpec
from pydantic import BaseModel, Field

from api.part_catalog import Part, PartCatalog


@dataclass(frozen=True)
class PartConstraint:
    package: str | None = None
    min_voltage_v: float | None = None
    max_voltage_v: float | None = None
    min_current_a: float | None = None
    interface: str | None = None


class PartCandidate(BaseModel):
    functional_role: str
    part: Part
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: list[str] = Field(default_factory=list)


class FunctionalBlockReview(BaseModel):
    functional_block: str
    candidates: list[PartCandidate] = Field(default_factory=list)


class PartReviewResult(BaseModel):
    block_reviews: list[FunctionalBlockReview] = Field(default_factory=list)


class PartResolver:
    def __init__(self, catalog: PartCatalog) -> None:
        self._catalog = catalog

    def review(
        self,
        circuit_spec: CircuitSpec,
        constraints: dict[str, PartConstraint] | None = None,
    ) -> PartReviewResult:
        constraints = constraints or {}
        reviews: list[FunctionalBlockReview] = []
        for block in circuit_spec.functional_blocks:
            role = self._infer_role(block.name)
            constraint = constraints.get(role, PartConstraint())
            candidates = self.resolve_candidates(
                role=role,
                circuit_spec=circuit_spec,
                constraint=constraint,
            )
            reviews.append(FunctionalBlockReview(functional_block=block.name, candidates=candidates))
        return PartReviewResult(block_reviews=reviews)

    def resolve_candidates(
        self,
        role: str,
        circuit_spec: CircuitSpec,
        constraint: PartConstraint,
    ) -> list[PartCandidate]:
        preferred = set(circuit_spec.preferred_parts)
        banned = set(circuit_spec.banned_parts)

        candidates: list[PartCandidate] = []
        for part in self._catalog.parts():
            if role not in part.functional_roles:
                continue
            if part.mpn in banned:
                continue

            rationale = [f"Matches functional role '{role}'."]
            confidence = 0.55
            if part.mpn in preferred:
                confidence += 0.25
                rationale.append("Listed in CircuitSpec preferred_parts.")

            if not self._is_package_compatible(part, constraint):
                continue
            if not self._is_voltage_compatible(part, constraint):
                continue
            if not self._is_current_compatible(part, constraint):
                continue
            if not self._is_interface_compatible(part, constraint):
                continue
            if not self._has_valid_symbol_footprint_mapping(part):
                continue

            rationale.append(f"Package compatible ({part.package.name}).")
            rationale.append("Voltage/current/interface constraints satisfied.")
            candidates.append(
                PartCandidate(
                    functional_role=role,
                    part=part,
                    confidence=min(confidence, 1.0),
                    rationale=rationale,
                )
            )

        return sorted(candidates, key=lambda item: item.confidence, reverse=True)

    @staticmethod
    def _infer_role(block_name: str) -> str:
        name = block_name.lower()
        if "regulator" in name or "power" in name:
            return "regulator"
        if "mcu" in name or "microcontroller" in name or "stm32" in name or "esp32" in name:
            return "mcu"
        if "esd" in name or "protection" in name:
            return "esd"
        if "connector" in name or "usb" in name:
            return "connector"
        return name.replace(" ", "-")

    @staticmethod
    def _has_valid_symbol_footprint_mapping(part: Part) -> bool:
        return all(
            (
                part.symbol_ref.library.strip(),
                part.symbol_ref.identifier.strip(),
                part.footprint_ref.library.strip(),
                part.footprint_ref.identifier.strip(),
            )
        )

    @staticmethod
    def _is_package_compatible(part: Part, constraint: PartConstraint) -> bool:
        return constraint.package is None or part.package.name.lower() == constraint.package.lower()

    @staticmethod
    def _is_voltage_compatible(part: Part, constraint: PartConstraint) -> bool:
        attrs = part.parametric_attributes
        if constraint.min_voltage_v is not None and attrs.max_input_voltage_v is not None:
            if attrs.max_input_voltage_v < constraint.min_voltage_v:
                return False
        if constraint.max_voltage_v is not None and attrs.min_input_voltage_v is not None:
            if attrs.min_input_voltage_v > constraint.max_voltage_v:
                return False
        return True

    @staticmethod
    def _is_current_compatible(part: Part, constraint: PartConstraint) -> bool:
        attrs = part.parametric_attributes
        if constraint.min_current_a is None:
            return True
        if attrs.max_current_a is None:
            return False
        return attrs.max_current_a >= constraint.min_current_a

    @staticmethod
    def _is_interface_compatible(part: Part, constraint: PartConstraint) -> bool:
        if constraint.interface is None:
            return True
        return (part.parametric_attributes.interface or "").lower() == constraint.interface.lower()
