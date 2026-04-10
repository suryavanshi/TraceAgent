from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, model_validator


class LifecycleStatus(str, Enum):
    ACTIVE = "active"
    NRND = "nrnd"
    EOL = "eol"


class SymbolRef(BaseModel):
    library: str = Field(min_length=1)
    identifier: str = Field(min_length=1)


class FootprintRef(BaseModel):
    library: str = Field(min_length=1)
    identifier: str = Field(min_length=1)


class Package(BaseModel):
    name: str = Field(min_length=1)


class ApprovedAlternate(BaseModel):
    mpn: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ApprovedAlternates(BaseModel):
    parts: list[ApprovedAlternate] = Field(default_factory=list)


class ParametricAttributes(BaseModel):
    min_input_voltage_v: float | None = None
    max_input_voltage_v: float | None = None
    output_voltage_v: float | None = None
    max_current_a: float | None = None
    interface: str | None = None
    extra: dict[str, str | float | int | bool] = Field(default_factory=dict)


class Part(BaseModel):
    mpn: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    description: str = Field(min_length=1)
    functional_roles: list[str] = Field(default_factory=list)
    symbol_ref: SymbolRef
    footprint_ref: FootprintRef
    package: Package
    parametric_attributes: ParametricAttributes = Field(default_factory=ParametricAttributes)
    lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE
    approved_alternates: ApprovedAlternates = Field(default_factory=ApprovedAlternates)

    @model_validator(mode="after")
    def ensure_symbol_footprint_are_bound(self) -> "Part":
        if not self.symbol_ref.identifier or not self.footprint_ref.identifier:
            raise ValueError("Symbol and footprint identifiers must be present for every part")
        return self


class PartCatalog(Protocol):
    def parts(self) -> list[Part]:
        ...


class LocalCuratedPartCatalog:
    def __init__(self, fixture_path: Path | None = None) -> None:
        self._fixture_path = fixture_path or (Path(__file__).parent / "fixtures" / "curated_catalog_v1.json")
        payload = json.loads(self._fixture_path.read_text(encoding="utf-8"))
        self._parts = [Part.model_validate(entry) for entry in payload["parts"]]

    def parts(self) -> list[Part]:
        return list(self._parts)
