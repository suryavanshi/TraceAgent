from __future__ import annotations

import subprocess
from pathlib import Path

from trace_kicad.compiler import SymbolPlacement


def export_schematic_svg(schematic_path: Path, output_path: Path, placements: list[SymbolPlacement]) -> Path:
    if _run_kicad_cli("svg", schematic_path, output_path):
        return output_path
    output_path.write_text(_fallback_svg(placements), encoding="utf-8")
    return output_path


def export_schematic_pdf(schematic_path: Path, output_path: Path, placements: list[SymbolPlacement]) -> Path:
    if _run_kicad_cli("pdf", schematic_path, output_path):
        return output_path
    output_path.write_bytes(_fallback_pdf_bytes(placements))
    return output_path


def _run_kicad_cli(kind: str, schematic_path: Path, output_path: Path) -> bool:
    cmd = [
        "kicad-cli",
        "sch",
        "export",
        kind,
        str(schematic_path),
        "--output",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _fallback_svg(placements: list[SymbolPlacement]) -> str:
    width = 900
    height = max(280, 60 + (len(placements) * 26))
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<text x="20" y="24" font-size="16" font-family="monospace">TraceAgent Schematic Preview</text>',
    ]
    for placement in placements:
        x = int(placement.x * 2.4)
        y = int(placement.y * 1.8)
        lines.append(f'<rect x="{x}" y="{y}" width="130" height="24" fill="#f6f8fa" stroke="#333"/>')
        lines.append(
            f'<text x="{x + 4}" y="{y + 16}" font-size="11" font-family="monospace">{placement.reference} ({placement.region})</text>'
        )
    lines.append("</svg>\n")
    return "\n".join(lines)


def _fallback_pdf_bytes(placements: list[SymbolPlacement]) -> bytes:
    # Minimal deterministic placeholder PDF payload.
    text = "TraceAgent schematic export\\n" + "\\n".join(f"{p.reference} {p.region}" for p in placements)
    return (
        b"%PDF-1.1\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj\n"
        + f"4 0 obj<</Length {len(text)+35}>>stream\nBT /F1 12 Tf 72 720 Td ({text}) Tj ET\nendstream endobj\n".encode("utf-8")
        + b"xref\n0 5\n0000000000 65535 f \n0000000010 00000 n \n0000000060 00000 n \n0000000115 00000 n \n0000000205 00000 n \n"
        + b"trailer<</Size 5/Root 1 0 R>>\nstartxref\n320\n%%EOF\n"
    )
