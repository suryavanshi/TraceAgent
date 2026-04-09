from __future__ import annotations

import json
from pathlib import Path

import pytest

from design_ir.models import CanonicalDesignBundle, CircuitSpec
from design_ir.serialization import diff_snapshots, from_json, to_canonical_json

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "example_design_sensor_node.json",
        "example_design_motor_controller.json",
        "example_design_gateway.json",
    ],
)
def test_example_design_bundle_valid(fixture_name: str) -> None:
    payload = json.loads((FIXTURES_DIR / fixture_name).read_text(encoding="utf-8"))
    bundle = CanonicalDesignBundle.validate_llm_payload(payload)
    assert bundle.schema_version == "1.0.0"


def test_invalid_llm_output_fails_loudly() -> None:
    with pytest.raises(ValueError, match="Invalid CircuitSpec payload"):
        CircuitSpec.validate_llm_payload(
            {
                "schema_version": "1.0.0",
                "product_name": "Bad Spec",
                "summary": "",
                "target_board_type": "rigid",
            }
        )


def test_snapshot_and_diff_helpers() -> None:
    base = CircuitSpec(
        product_name="A",
        summary="alpha",
        target_board_type="rigid",
    )
    changed = base.model_copy(update={"open_questions": ["Confirm connector"]})

    payload = to_canonical_json(base)
    hydrated = from_json(CircuitSpec, payload)
    delta = diff_snapshots(base, changed)

    assert hydrated == base
    assert "Confirm connector" in delta
