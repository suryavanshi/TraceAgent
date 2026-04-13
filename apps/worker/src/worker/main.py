from __future__ import annotations

import os
import time
from pathlib import Path

from trace_verification import explain_finding, normalize_report, run_kicad_erc

from worker.freerouting_job import run_freerouting_job


def run_erc_verification_job(project_file: str) -> dict:
    raw_output = run_kicad_erc(Path(project_file))
    normalized_output = normalize_report(raw_output)
    explanations = [{"code": finding["code"], "plain_english": explain_finding(finding)} for finding in normalized_output.get("findings", [])]
    return {
        "status": "completed" if raw_output.get("status") == "completed" else "failed",
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
