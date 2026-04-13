from __future__ import annotations

import re
from pathlib import Path


def _required_trace_width_mm(current_target_amps: float) -> float:
    return max(0.2, current_target_amps * 0.25)


def run_manufacturability_checks(pcb_file: Path, *, current_target_amps: float = 1.0) -> dict:
    if not pcb_file.exists():
        return {
            "tool": "manufacturability-heuristics",
            "status": "failed",
            "issues": [],
            "error": f"pcb file missing: {pcb_file}",
        }

    text = pcb_file.read_text(encoding="utf-8")
    issues: list[dict] = []

    widths = [float(raw) for raw in re.findall(r"\(segment\b[^\n]*\(width\s+([0-9.]+)\)", text)]
    min_width = min(widths) if widths else None
    required_width = _required_trace_width_mm(current_target_amps)
    if min_width is not None and min_width < required_width:
        issues.append(
            {
                "id": "MFG_TRACE_WIDTH",
                "severity": "warning",
                "message": (
                    f"Minimum routed trace width is {min_width:.3f} mm, below heuristic "
                    f"{required_width:.3f} mm target for {current_target_amps:.2f} A."
                ),
                "evidence": {
                    "min_trace_width_mm": min_width,
                    "required_trace_width_mm": required_width,
                    "current_target_amps": current_target_amps,
                    "segment_count": len(widths),
                },
            }
        )

    testpoint_count = len(re.findall(r'\(property\s+"Reference"\s+"TP\d+"', text))
    net_count = len(set(re.findall(r"\(net\s+\d+\s+\"([^\"]+)\"", text)))
    if net_count >= 8 and testpoint_count < 2:
        issues.append(
            {
                "id": "MFG_TESTPOINT_SCARCITY",
                "severity": "warning",
                "message": (
                    f"Only {testpoint_count} testpoints found for {net_count} nets; probing/debug coverage may be limited."
                ),
                "evidence": {"testpoint_count": testpoint_count, "net_count": net_count},
            }
        )

    rect_match = re.search(
        r"\(gr_rect\s+\(start\s+([0-9.\-]+)\s+([0-9.\-]+)\)\s+\(end\s+([0-9.\-]+)\s+([0-9.\-]+)\)\s+\(layer\s+\"Edge.Cuts\"",
        text,
    )
    board_box = None
    if rect_match:
        x1, y1, x2, y2 = (float(rect_match.group(i)) for i in range(1, 5))
        board_box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    footprints = [
        (float(x), float(y))
        for x, y in re.findall(r"\(footprint\s+\"[^\"]+\"[\s\S]*?\(at\s+([0-9.\-]+)\s+([0-9.\-]+)", text)
    ]
    edge_clearance_threshold = 1.0
    if board_box and footprints:
        left, top, right, bottom = board_box
        near_edge = 0
        for x, y in footprints:
            clearance = min(abs(x - left), abs(x - right), abs(y - top), abs(y - bottom))
            if clearance < edge_clearance_threshold:
                near_edge += 1
        if near_edge:
            issues.append(
                {
                    "id": "MFG_EDGE_CLEARANCE",
                    "severity": "warning",
                    "message": f"{near_edge} footprint(s) appear within {edge_clearance_threshold:.1f} mm of board edge.",
                    "evidence": {
                        "near_edge_count": near_edge,
                        "edge_clearance_threshold_mm": edge_clearance_threshold,
                        "board_box": board_box,
                    },
                }
            )

    silk_widths = [float(raw) for raw in re.findall(r"\(fp_line\b[^\n]*\(layer\s+\"F\.SilkS\"\)[^\n]*\(width\s+([0-9.]+)\)", text)]
    if silk_widths and min(silk_widths) < 0.12:
        issues.append(
            {
                "id": "MFG_SILKSCREEN_COLLISION_RISK",
                "severity": "info",
                "message": "Very thin silkscreen lines may violate fab limits or overlap solderable features.",
                "evidence": {"min_silk_width_mm": min(silk_widths), "recommended_min_width_mm": 0.12},
            }
        )

    return {
        "tool": "manufacturability-heuristics",
        "status": "completed",
        "issues": issues,
        "input": {"pcb_file": str(pcb_file), "current_target_amps": current_target_amps},
    }
