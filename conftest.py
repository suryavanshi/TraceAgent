from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent

PYTHON_SRC_PATHS = [
    ROOT / "apps" / "api" / "src",
    ROOT / "apps" / "worker" / "src",
    ROOT / "packages" / "schemas" / "python" / "src",
    ROOT / "packages" / "design-ir" / "src",
    ROOT / "packages" / "llm" / "src",
    ROOT / "packages" / "kicad" / "src",
    ROOT / "packages" / "verification" / "src",
]

for path in PYTHON_SRC_PATHS:
    sys.path.insert(0, str(path))

os.environ.setdefault("TRACE_AUTH_REQUIRED", "false")
