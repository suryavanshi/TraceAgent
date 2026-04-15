from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse


class InMemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        bucket = self._events[key]
        while bucket and bucket[0] <= now - self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


def install_rate_limiting(app: FastAPI) -> None:
    limit = int(os.getenv("TRACE_RATE_LIMIT", "120"))
    window = int(os.getenv("TRACE_RATE_WINDOW_SECONDS", "60"))
    limiter = InMemoryRateLimiter(limit=limit, window_seconds=window)

    @app.middleware("http")
    async def enforce_rate_limit(request: Request, call_next):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        actor = request.headers.get("x-api-token", "anonymous")
        key = f"{actor}:{request.url.path}"
        if not limiter.allow(key):
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "blocker": "Too many design-changing actions in a short window.",
                    "retry_after_seconds": window,
                },
            )
        return await call_next(request)
