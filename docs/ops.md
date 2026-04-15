# TraceAgent Production Hardening Ops Guide

## Security and Authorization
- API auth is controlled by `TRACE_AUTH_REQUIRED` (default: `true`).
- Tokens are provided by `TRACE_API_TOKENS` in the format:
  - `token:subject|role,token2:subject2|role2`
- Supported roles: `viewer`, `editor`, `admin`.
- Design-changing actions require `editor` or `admin`.

## Audit Logging
- All design-changing routes emit structured audit events.
- Log path: `TRACE_AUDIT_LOG_PATH` (default `/tmp/traceagent/audit/audit.log`).
- Events include actor, action, resource, status, and metadata.

## Rate Limiting
- Non-GET API calls are rate-limited per token + route.
- `TRACE_RATE_LIMIT` (default `120`) within `TRACE_RATE_WINDOW_SECONDS` (default `60`).
- Exceeding requests return `429` with blocker metadata.

## Worker Reliability
- Worker tasks use retries + timeout wrappers.
- `WORKER_MAX_RETRIES` (default `3`)
- `WORKER_JOB_TIMEOUT_SECONDS` (default `120`)
- `WORKER_RETRY_BASE_DELAY_SECONDS` (default `1.0`)
- Permanent task failures are written to dead-letter directory:
  - `WORKER_DEAD_LETTER_DIR` (default `/tmp/traceagent/dead-letter`)

## Artifact Retention
- Manual prune endpoint: `POST /ops/artifacts/prune` (admin only).
- Pruning behavior:
  - delete generated/verification/release directories older than `TRACE_ARTIFACT_RETENTION_DAYS` (default `30`)
  - keep at least `TRACE_ARTIFACT_MIN_RELEASES` (default `3`) newest release folders

## Observability
- Request tracing headers:
  - `x-request-id` returned on all responses
  - `x-latency-ms` returned on all responses
- Metrics endpoint: `GET /metrics` in Prometheus text format.

## Seed Projects
- Available seeds from `GET /seed-projects`:
  - ESP32 sensor board
  - STM32 CAN board
  - USB-C UART adapter
- Apply with `POST /projects/{project_id}/seed/{seed_slug}`

## UI Error Surfaces
- UI now parses API blocker details and displays blocker context.
- Verification failures are shown as release blockers.
- Partial failure data remains visible and is not hidden.
