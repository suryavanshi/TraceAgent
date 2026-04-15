from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass

from fastapi import FastAPI, Request
from starlette.responses import PlainTextResponse

logger = logging.getLogger("traceagent.api")


@dataclass
class MetricsRegistry:
    request_counter: Counter[str]
    error_counter: Counter[str]
    latency_ms_total: Counter[str]


metrics = MetricsRegistry(Counter(), Counter(), Counter())


def install_observability(app: FastAPI) -> None:
    @app.middleware("http")
    async def instrument_requests(request: Request, call_next):
        started = time.perf_counter()
        method = request.method
        path = request.url.path
        key = f"{method} {path}"
        request_id = request.headers.get("x-request-id", f"req-{int(started * 1000)}")
        try:
            response = await call_next(request)
        except Exception:
            metrics.error_counter[key] += 1
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        metrics.request_counter[key] += 1
        metrics.latency_ms_total[key] += elapsed_ms
        if response.status_code >= 500:
            metrics.error_counter[key] += 1
        response.headers["x-request-id"] = request_id
        response.headers["x-latency-ms"] = str(elapsed_ms)
        logger.info("request method=%s path=%s status=%s latency_ms=%s request_id=%s", method, path, response.status_code, elapsed_ms, request_id)
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics_endpoint() -> PlainTextResponse:
        lines: list[str] = []
        for key, count in metrics.request_counter.items():
            lines.append(f'traceagent_requests_total{{route="{key}"}} {count}')
        for key, count in metrics.error_counter.items():
            lines.append(f'traceagent_request_errors_total{{route="{key}"}} {count}')
        for key, count in metrics.latency_ms_total.items():
            lines.append(f'traceagent_request_latency_ms_sum{{route="{key}"}} {count}')
        return PlainTextResponse("\n".join(lines) + "\n")
