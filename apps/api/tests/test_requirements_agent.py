from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.db import Base, get_db
from api.main import app
from api.requirements_agent import RequirementsAgent, RequirementsChatMessage, RuleBasedRequirementsProvider


def build_test_client(tmp_path: Path) -> TestClient:
    db_url = f"sqlite:///{tmp_path / 'test_requirements.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Session:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_requirements_agent_golden_prompts() -> None:
    agent = RequirementsAgent(provider=RuleBasedRequirementsProvider())

    prompts = [
        "Make an ESP32 environmental sensor board with USB-C power and I2C sensors.",
        "Create a small STM32 board with CAN and 12V to 5V power regulation.",
        "Design a LiPo-powered BLE tracker board under 30x30mm.",
    ]

    results = [
        agent.derive(chat_history=[], latest_user_request=prompt)
        for prompt in prompts
    ]

    assert any(interface.name == "I2C" for interface in results[0].proposed_circuit_spec.interfaces)
    assert any(rail.name == "5V rail" for rail in results[1].proposed_circuit_spec.power_rails)
    assert any("30mm x 30mm" in mc for mc in results[2].proposed_circuit_spec.mechanical_constraints)


def test_requirements_agent_adds_missing_information_questions() -> None:
    agent = RequirementsAgent(provider=RuleBasedRequirementsProvider())
    result = agent.derive(
        chat_history=[RequirementsChatMessage(role="user", content="Need a compact BLE board")],
        latest_user_request="Design a small BLE tracker board",
    )

    assert any("voltage" in question.lower() for question in result.open_questions)
    assert any("dimensions" in question.lower() for question in result.open_questions)


def test_requirements_derive_endpoint(tmp_path: Path) -> None:
    client = build_test_client(tmp_path)
    project = client.post(
        "/projects",
        json={
            "owner_email": "req-agent@example.com",
            "name": "requirements-target",
        },
    ).json()

    response = client.post(
        f"/projects/{project['id']}/requirements/derive",
        json={
            "chat_history": [
                {"role": "user", "content": "Need low-power telemetry"},
                {"role": "assistant", "content": "Do you need CAN?"},
            ],
            "latest_user_request": "Create a small STM32 board with CAN and 12V to 5V power regulation.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["proposed_circuit_spec"]["target_board_type"] == "controller"
    assert any("current limits" in q.lower() for q in payload["open_questions"])
