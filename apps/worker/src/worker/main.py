from __future__ import annotations

import os
import time
from pathlib import Path

from trace_verification import (
    explain_finding,
    normalize_verification_suite,
    run_kicad_drc,
    run_kicad_erc,
    run_manufacturability_checks,
)

from worker.freerouting_job import run_freerouting_job


def run_erc_verification_job(project_file: str) -> dict:
    raw_erc = run_kicad_erc(Path(project_file))
    normalized_output = normalize_verification_suite({"erc": raw_erc})
    explanations = [{"code": finding["code"], "plain_english": explain_finding(finding)} for finding in normalized_output.get("findings", [])]
    return {
        "status": "completed" if raw_erc.get("status") == "completed" else "failed",
        "raw_output": {"erc": raw_erc},
        "normalized_output": normalized_output,
        "explanations": explanations,
    }


def run_pcb_verification_job(project_file: str, pcb_file: str, *, current_target_amps: float = 1.0) -> dict:
    raw_erc = run_kicad_erc(Path(project_file))
    raw_drc = run_kicad_drc(Path(pcb_file))
    raw_manufacturability = run_manufacturability_checks(Path(pcb_file), current_target_amps=current_target_amps)
    raw_output = {"erc": raw_erc, "drc": raw_drc, "manufacturability": raw_manufacturability}
    normalized_output = normalize_verification_suite(raw_output)
    explanations = [{"code": finding["code"], "plain_english": explain_finding(finding)} for finding in normalized_output.get("findings", [])]
    statuses = [raw_erc.get("status"), raw_drc.get("status"), raw_manufacturability.get("status")]
    return {
        "status": "completed" if all(status == "completed" for status in statuses) else "failed",
        "raw_output": raw_output,
        "normalized_output": normalized_output,
        "explanations": explanations,
    }


def run() -> None:
    worker_name = os.getenv("WORKER_NAME", "trace-worker")
    interval_seconds = int(os.getenv("WORKER_POLL_INTERVAL", "10"))

    print(f"[{worker_name}] started")
    while True:
        print(f"[{worker_name}] heartbeat")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run()
