from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import TypeVar

from .models import VersionedModel

ModelT = TypeVar("ModelT", bound=VersionedModel)


def to_canonical_json(model: VersionedModel) -> str:
    return model.model_dump_json(indent=2, by_alias=True, exclude_none=True)


def from_json(model_type: type[ModelT], payload: str) -> ModelT:
    return model_type.validate_llm_payload(json.loads(payload))


def write_snapshot(model: VersionedModel, path: Path) -> None:
    path.write_text(to_canonical_json(model) + "\n", encoding="utf-8")


def diff_snapshots(old: VersionedModel, new: VersionedModel, from_name: str = "old", to_name: str = "new") -> str:
    old_lines = to_canonical_json(old).splitlines(keepends=True)
    new_lines = to_canonical_json(new).splitlines(keepends=True)
    return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=from_name, tofile=to_name))
