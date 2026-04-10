from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    owner_email: str
    owner_display_name: str | None = None
    name: str
    description: str | None = None


class ProjectResponse(BaseModel):
    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    artifact_root_dir: str
    snapshot_repo_dir: str
    created_at: datetime


class SnapshotFile(BaseModel):
    path: str = Field(min_length=1)
    content: str


class SnapshotCreate(BaseModel):
    title: str
    notes: str | None = None
    files: list[SnapshotFile] = Field(default_factory=list)


class SnapshotResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    notes: str | None
    artifact_dir: str
    git_commit_hash: str
    created_at: datetime


class SnapshotRevertResponse(BaseModel):
    project_id: UUID
    reverted_to_snapshot_id: UUID
    git_commit_hash: str


class RequirementsChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1)


class RequirementsDeriveRequest(BaseModel):
    latest_user_request: str = Field(min_length=1)
    chat_history: list[RequirementsChatMessage] = Field(default_factory=list)


class RequirementsDeriveResponse(BaseModel):
    proposed_circuit_spec: dict
    summary: str
    open_questions: list[str] = Field(default_factory=list)
