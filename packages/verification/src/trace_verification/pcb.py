from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _load_issues(output_json: Path) -> list[dict]:
    if not output_json.exists():
        return []
    try:
        payload = json.loads(output_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(payload, dict):
        if isinstance(payload.get("issues"), list):
            return [item for item in payload["issues"] if isinstance(item, dict)]
        if isinstance(payload.get("violations"), list):
            return [item for item in payload["violations"] if isinstance(item, dict)]
    return []


def _derive_subchecks(issues: list[dict]) -> dict[str, list[dict]]:
    unconnected: list[dict] = []
    courtyard: list[dict] = []

    for issue in issues:
        issue_text = f"{issue.get('id', '')} {issue.get('code', '')} {issue.get('message', '')}".lower()
        if "unconnected" in issue_text or "dangling" in issue_text:
            unconnected.append(issue)
        if "courtyard" in issue_text or "overlap" in issue_text:
            courtyard.append(issue)

    return {
        "unconnected_nets": unconnected,
        "courtyard_overlap": courtyard,
    }


def run_kicad_drc(pcb_file: Path) -> dict:
    output_json = pcb_file.with_suffix(".drc.json")
    cmd = ["kicad-cli", "pcb", "drc", str(pcb_file), "--format", "json", "--output", str(output_json)]
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return {
            "tool": "kicad-drc",
            "status": "failed",
            "issues": [],
            "error": "kicad-cli not available",
            "command": cmd,
            "derived_checks": {"unconnected_nets": [], "courtyard_overlap": []},
        }

    issues = _load_issues(output_json)
    return {
        "tool": "kicad-drc",
        "status": "completed" if completed.returncode == 0 else "failed",
        "issues": issues,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "returncode": completed.returncode,
        "command": cmd,
        "derived_checks": _derive_subchecks(issues),
    }
