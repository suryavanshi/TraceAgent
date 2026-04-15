from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class AuthContext:
    subject: str
    role: str


def _is_auth_required() -> bool:
    return os.getenv("TRACE_AUTH_REQUIRED", "true").lower() in {"1", "true", "yes", "on"}


def _token_map() -> dict[str, AuthContext]:
    configured = os.getenv("TRACE_API_TOKENS", "")
    token_map: dict[str, AuthContext] = {}
    for entry in configured.split(","):
        raw = entry.strip()
        if not raw:
            continue
        token, _, identity = raw.partition(":")
        subject, _, role = identity.partition("|")
        if token and subject and role:
            token_map[token] = AuthContext(subject=subject, role=role)
    if token_map:
        return token_map
    return {
        "trace-admin-token": AuthContext(subject="ops@traceagent.local", role="admin"),
        "trace-editor-token": AuthContext(subject="engineer@traceagent.local", role="editor"),
        "trace-viewer-token": AuthContext(subject="viewer@traceagent.local", role="viewer"),
    }


def require_auth(x_api_token: str | None = Header(default=None)) -> AuthContext:
    if not _is_auth_required():
        return AuthContext(subject="dev-local", role="admin")
    if not x_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Token header")
    principal = _token_map().get(x_api_token)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    return principal


def require_role(auth: AuthContext, roles: Iterable[str]) -> AuthContext:
    allowed = set(roles)
    if auth.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires one of roles: {sorted(allowed)}")
    return auth
