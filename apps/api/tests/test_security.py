from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.db import Base, get_db
from api.main import app


def build_test_client(tmp_path: Path) -> TestClient:
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Session:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_auth_enforced_when_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRACE_AUTH_REQUIRED", "true")
    client = build_test_client(tmp_path)
    response = client.post(
        "/projects",
        json={"owner_email": "secure@example.com", "name": "secure", "description": "secure"},
    )
    assert response.status_code == 401
