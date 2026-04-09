from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db import Base, engine, get_db
from api.git_snapshots import GitSnapshotRepository
from api.models import DesignSnapshot, Project, User
from api.schemas import (
    ProjectCreate,
    ProjectResponse,
    SnapshotCreate,
    SnapshotResponse,
    SnapshotRevertResponse,
)
from api.storage import LocalFilesystemStorage

app = FastAPI(title="TraceAgent API", version="0.1.0")

STORAGE_BASE = os.getenv("ARTIFACT_STORAGE_BASE", "/tmp/traceagent/artifacts")
SNAPSHOT_BASE = os.getenv("SNAPSHOT_REPO_BASE", "/tmp/traceagent/snapshots")
storage = LocalFilesystemStorage(STORAGE_BASE)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api", "version": app.version}


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    return {"status": "ok", "service": "api", "checks": "pending"}


@app.post("/projects", response_model=ProjectResponse)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    user = db.scalar(select(User).where(User.email == payload.owner_email))
    if user is None:
        user = User(email=payload.owner_email, display_name=payload.owner_display_name)
        db.add(user)
        db.flush()

    artifact_dir = f"projects/{user.id}/{payload.name}"
    snapshot_repo_dir = str(Path(SNAPSHOT_BASE) / str(user.id) / payload.name)

    project = Project(
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
        artifact_root_dir=artifact_dir,
        snapshot_repo_dir=snapshot_repo_dir,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    GitSnapshotRepository(project.snapshot_repo_dir)
    return project


@app.get("/projects", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())).all())


@app.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.post("/projects/{project_id}/snapshots", response_model=SnapshotResponse)
def create_snapshot(project_id: UUID, payload: SnapshotCreate, db: Session = Depends(get_db)) -> DesignSnapshot:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    artifact_dir = f"{project.artifact_root_dir}/snapshots/{payload.title.replace(' ', '_').lower()}"
    for file in payload.files:
        storage.write_text(artifact_dir, file.path, file.content)
        Path(project.snapshot_repo_dir).mkdir(parents=True, exist_ok=True)
        target = Path(project.snapshot_repo_dir) / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")

    git_repo = GitSnapshotRepository(project.snapshot_repo_dir)
    commit_hash = git_repo.commit_all(f"snapshot: {payload.title}")
    snapshot = DesignSnapshot(
        project_id=project.id,
        title=payload.title,
        notes=payload.notes,
        artifact_dir=artifact_dir,
        git_commit_hash=commit_hash,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


@app.get("/projects/{project_id}/snapshots", response_model=list[SnapshotResponse])
def list_snapshots(project_id: UUID, db: Session = Depends(get_db)) -> list[DesignSnapshot]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list(
        db.scalars(select(DesignSnapshot).where(DesignSnapshot.project_id == project_id).order_by(DesignSnapshot.created_at.desc())).all()
    )


@app.post("/projects/{project_id}/snapshots/{snapshot_id}/revert", response_model=SnapshotRevertResponse)
def revert_snapshot(project_id: UUID, snapshot_id: UUID, db: Session = Depends(get_db)) -> SnapshotRevertResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    snapshot = db.get(DesignSnapshot, snapshot_id)
    if snapshot is None or snapshot.project_id != project.id:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    git_repo = GitSnapshotRepository(project.snapshot_repo_dir)
    current_hash = git_repo.revert_to(snapshot.git_commit_hash)
    return SnapshotRevertResponse(
        project_id=project.id,
        reverted_to_snapshot_id=snapshot.id,
        git_commit_hash=current_hash,
    )
