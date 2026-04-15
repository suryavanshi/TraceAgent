from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class RetentionResult:
    deleted_paths: list[str]
    skipped_paths: list[str]


def prune_artifacts(base_dir: str) -> RetentionResult:
    root = Path(base_dir)
    retention_days = int(os.getenv("TRACE_ARTIFACT_RETENTION_DAYS", "30"))
    min_releases = int(os.getenv("TRACE_ARTIFACT_MIN_RELEASES", "3"))
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    deleted: list[str] = []
    skipped: list[str] = []

    release_dirs = sorted([path for path in root.glob("**/releases/*") if path.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    pinned = set(release_dirs[:min_releases])

    for path in root.glob("**/*"):
        if not path.is_dir():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified > cutoff or path in pinned:
            skipped.append(str(path))
            continue
        if "generated" in path.parts or "verification" in path.parts or "releases" in path.parts:
            shutil.rmtree(path, ignore_errors=True)
            deleted.append(str(path))

    return RetentionResult(deleted_paths=deleted, skipped_paths=skipped)
