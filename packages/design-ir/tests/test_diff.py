from design_ir.diff import diff_design
from design_ir.models import DesignIR


def test_diff_design_components() -> None:
    previous = DesignIR(design_id="d1", revision=1, components=["R1"])
    current = DesignIR(design_id="d1", revision=2, components=["R1", "C1"])
    result = diff_design(previous, current)
    assert result["added_components"] == ["C1"]
    assert result["removed_components"] == []
