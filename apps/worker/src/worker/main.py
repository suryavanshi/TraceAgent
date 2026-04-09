from __future__ import annotations

import os
import time


def run() -> None:
    worker_name = os.getenv("WORKER_NAME", "trace-worker")
    interval_seconds = int(os.getenv("WORKER_POLL_INTERVAL", "10"))

    print(f"[{worker_name}] started")
    while True:
        print(f"[{worker_name}] heartbeat")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run()
