from __future__ import annotations

import json
import subprocess
from pathlib import Path


def run_kicad_erc(project_file: Path) -> dict:
    output_json = project_file.with_suffix(".erc.json")
    cmd = ["kicad-cli", "sch", "erc", str(project_file), "--format", "json", "--output", str(output_json)]
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        return {
            "tool": "kicad-erc",
            "status": "failed",
            "issues": [],
            "error": "kicad-cli not available",
            "command": cmd,
        }

    raw_stdout = completed.stdout.strip()
    raw_stderr = completed.stderr.strip()
    issues: list[dict] = []
    if output_json.exists():
        try:
            payload = json.loads(output_json.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                if isinstance(payload.get("issues"), list):
                    issues = [item for item in payload["issues"] if isinstance(item, dict)]
                elif isinstance(payload.get("violations"), list):
                    issues = [item for item in payload["violations"] if isinstance(item, dict)]
        except json.JSONDecodeError:
            pass

    status = "completed" if completed.returncode == 0 else "failed"
    return {
        "tool": "kicad-erc",
        "status": status,
        "issues": issues,
        "stdout": raw_stdout,
        "stderr": raw_stderr,
        "returncode": completed.returncode,
        "command": cmd,
    }
