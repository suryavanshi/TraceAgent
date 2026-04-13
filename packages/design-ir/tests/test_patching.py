from __future__ import annotations

import json
from pathlib import Path

import pytest

from design_ir.models import (
    CanonicalDesignBundle,
    ImpactDomain,
    PatchCategory,
    PatchImpactAnalysis,
    PatchOperation,
    PatchPlan,
)
from design_ir.patching import PatchAgent, PatchApplicationError, PatchEngine, PatchSession

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def bundle() -> CanonicalDesignBundle:
    payload = json.loads((FIXTURES_DIR / "example_design_sensor_node.json").read_text(encoding="utf-8"))
    return CanonicalDesignBundle.validate_llm_payload(payload)


@pytest.mark.parametrize(
    ("instruction", "expected_category", "expected_domain"),
    [
        ("add a component for led status", PatchCategory.ADD_REMOVE_COMPONENT, ImpactDomain.SCHEMATIC_ONLY),
        ("remove the extra regulator", PatchCategory.ADD_REMOVE_COMPONENT, ImpactDomain.SCHEMATIC_ONLY),
        ("swap MCU with lower power variant", PatchCategory.SWAP_PART, ImpactDomain.BOTH),
        ("rename net from SDA to I2C_SDA", PatchCategory.RENAME_NET, ImpactDomain.SCHEMATIC_ONLY),
        ("change power rail to 1V8", PatchCategory.CHANGE_POWER_RAIL_VALUE, ImpactDomain.SCHEMATIC_ONLY),
        ("move connector J1 to right edge", PatchCategory.MOVE_CONNECTOR, ImpactDomain.BOTH),
        ("resize board to 60x40", PatchCategory.RESIZE_BOARD, ImpactDomain.BOTH),
        ("widen trace class for motor current", PatchCategory.WIDEN_TRACE_CLASS, ImpactDomain.BOTH),
        ("add test point for reset net", PatchCategory.ADD_TEST_POINTS, ImpactDomain.BOTH),
        ("add protection circuitry on usb", PatchCategory.ADD_PROTECTION_CIRCUITRY, ImpactDomain.SCHEMATIC_ONLY),
        ("add component decoupling cap", PatchCategory.ADD_REMOVE_COMPONENT, ImpactDomain.SCHEMATIC_ONLY),
        ("remove debug led", PatchCategory.ADD_REMOVE_COMPONENT, ImpactDomain.SCHEMATIC_ONLY),
        ("swap op-amp", PatchCategory.SWAP_PART, ImpactDomain.BOTH),
        ("rename net ALERT", PatchCategory.RENAME_NET, ImpactDomain.SCHEMATIC_ONLY),
        ("power rail 5V should be 12V", PatchCategory.CHANGE_POWER_RAIL_VALUE, ImpactDomain.SCHEMATIC_ONLY),
        ("move connector for antenna", PatchCategory.MOVE_CONNECTOR, ImpactDomain.BOTH),
        ("resize board outline", PatchCategory.RESIZE_BOARD, ImpactDomain.BOTH),
        ("widen trace for VBUS", PatchCategory.WIDEN_TRACE_CLASS, ImpactDomain.BOTH),
        ("please add test points", PatchCategory.ADD_TEST_POINTS, ImpactDomain.BOTH),
        ("add protection for input", PatchCategory.ADD_PROTECTION_CIRCUITRY, ImpactDomain.SCHEMATIC_ONLY),
    ],
)
def test_patch_agent_classifies_patch_scenarios(
    instruction: str,
    expected_category: PatchCategory,
    expected_domain: ImpactDomain,
) -> None:
    plan = PatchAgent().plan_patch(instruction)
    assert plan.category == expected_category
    assert plan.impact_analysis.domain == expected_domain
    assert plan.provenance[0].instruction == instruction


def test_patch_engine_applies_and_marks_verification_invalid_for_high_impact(bundle: CanonicalDesignBundle) -> None:
    plan = PatchPlan(
        user_intent="move connector J1",
        affected_objects=["board_ir.fixed_edge_connectors"],
        operations=[PatchOperation(op="move", path="board_ir.fixed_edge_connectors")],
        impact_scope="global",
        requires_confirmation=True,
        category=PatchCategory.MOVE_CONNECTOR,
        impact_analysis=PatchImpactAnalysis(
            domain=ImpactDomain.BOTH,
            requires_replacement=True,
            requires_rerouting=True,
            requires_reverification=True,
        ),
    )

    result = PatchEngine().apply(bundle, plan)

    assert result.recompiled_artifacts == ["schematic", "board"]
    assert result.updated_bundle.verification_report.tool == "patch-engine"
    assert result.updated_bundle.verification_report.findings[-1].code == "PATCH_REVERIFY_REQUIRED"
    assert result.diff.machine_readable["category"] == "move_connector"


def test_patch_engine_is_transactional_on_invalid_operation(bundle: CanonicalDesignBundle) -> None:
    original = bundle.model_copy(deep=True)
    plan = PatchPlan(
        user_intent="broken op",
        affected_objects=["bad.path"],
        operations=[PatchOperation(op="update", path="unknown_root.field")],
        impact_scope="local",
        requires_confirmation=False,
    )

    with pytest.raises(PatchApplicationError):
        PatchEngine().apply(bundle, plan)

    assert bundle == original


def test_patch_session_undo_redo(bundle: CanonicalDesignBundle) -> None:
    session = PatchSession(current=bundle)
    engine = PatchEngine()
    plan = PatchPlan(
        user_intent="add protection circuitry",
        affected_objects=["schematic_ir.component_instances"],
        operations=[
            PatchOperation(
                op="add",
                path="schematic_ir.component_instances",
                value={
                    "instance_id": "inst_esd_1",
                    "symbol_id": "sym_esd_1",
                    "reference": "D99",
                    "value": "ESD",
                    "properties": {},
                },
            )
        ],
        impact_scope="sheet",
        requires_confirmation=False,
        category=PatchCategory.ADD_PROTECTION_CIRCUITRY,
    )

    applied = session.apply(engine, plan)
    after_apply = applied.updated_bundle.model_copy(deep=True)
    undone = session.undo()
    redone = session.redo()

    assert undone != after_apply
    assert redone == after_apply
