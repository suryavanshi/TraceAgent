from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("traceagent.audit")


@dataclass
class AuditEvent:
    actor: str
    action: str
    resource: str
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditLogger:
    def __init__(self) -> None:
        self._path = Path(os.getenv("TRACE_AUDIT_LOG_PATH", "/tmp/traceagent/audit/audit.log"))

    def write(self, event: AuditEvent) -> None:
        payload = asdict(event)
        payload["timestamp"] = datetime.now(UTC).isoformat()
        serialized = json.dumps(payload, sort_keys=True)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(serialized + "\n")
        logger.info("audit_event %s", serialized)


audit_logger = AuditLogger()
