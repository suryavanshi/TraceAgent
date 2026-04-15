from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    attempts: int
    timeout_seconds: int
    base_delay_seconds: float


def get_retry_config() -> RetryConfig:
    return RetryConfig(
        attempts=int(os.getenv("WORKER_MAX_RETRIES", "3")),
        timeout_seconds=int(os.getenv("WORKER_JOB_TIMEOUT_SECONDS", "120")),
        base_delay_seconds=float(os.getenv("WORKER_RETRY_BASE_DELAY_SECONDS", "1.0")),
    )


def _write_dead_letter(task_name: str, error: str, payload: dict) -> None:
    root = Path(os.getenv("WORKER_DEAD_LETTER_DIR", "/tmp/traceagent/dead-letter"))
    root.mkdir(parents=True, exist_ok=True)
    entry = {
        "task_name": task_name,
        "error": error,
        "payload": payload,
        "created_at": datetime.now(UTC).isoformat(),
    }
    filename = f"{task_name}_{int(time.time() * 1000)}.json"
    (root / filename).write_text(json.dumps(entry, indent=2, sort_keys=True), encoding="utf-8")


def run_with_retries(task_name: str, fn: Callable[[], T], *, payload: dict) -> T:
    config = get_retry_config()
    last_error: Exception | None = None
    for attempt in range(1, config.attempts + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(fn)
                return future.result(timeout=config.timeout_seconds)
        except TimeoutError as exc:
            last_error = TimeoutError(f"{task_name} timed out after {config.timeout_seconds}s")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt < config.attempts:
            time.sleep(config.base_delay_seconds * attempt)

    assert last_error is not None
    _write_dead_letter(task_name, str(last_error), payload)
    raise RuntimeError(f"{task_name} failed after {config.attempts} attempts") from last_error
