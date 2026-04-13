from pathlib import Path

from trace_verification.manufacturability import run_manufacturability_checks


def test_manufacturability_flags_expected_issues(tmp_path: Path) -> None:
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text(
        """
(kicad_pcb
  (gr_rect (start 0 0) (end 20 20) (layer "Edge.Cuts"))
  (net 1 "GND")
  (net 2 "VCC")
  (net 3 "N1")
  (net 4 "N2")
  (net 5 "N3")
  (net 6 "N4")
  (net 7 "N5")
  (net 8 "N6")
  (footprint "Resistor_SMD:R_0603" (layer "F.Cu") (at 0.5 0.5)
    (property "Reference" "R1"))
  (segment (start 0 0) (end 1 1) (width 0.15) (layer "F.Cu") (net 1))
  (fp_line (start 0 0) (end 1 0) (layer "F.SilkS") (width 0.10))
)
        """,
        encoding="utf-8",
    )

    result = run_manufacturability_checks(pcb, current_target_amps=1.0)
    codes = {issue["id"] for issue in result["issues"]}
    assert "MFG_TRACE_WIDTH" in codes
    assert "MFG_TESTPOINT_SCARCITY" in codes
    assert "MFG_EDGE_CLEARANCE" in codes
    assert "MFG_SILKSCREEN_COLLISION_RISK" in codes
