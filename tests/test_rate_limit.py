from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from emporio.api import AppContainer, create_app
from emporio.api.rate_limit import SlidingWindowRateLimiter
from emporio.config import Settings
from emporio.etl.loader import load_raw_dir

RAW_DIR = Path("data/raw")


def _fake_model() -> FunctionModel:
    def responder(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="Resposta de teste.")])

    async def streamer(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[Any]:
        yield "Resposta de teste."

    return FunctionModel(responder, stream_function=streamer)


def _login_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_sliding_window_rate_limiter_enforces_limit_and_recovers() -> None:
    now = [100.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])

    assert limiter.check("u1", limit=2, window_seconds=60) == (True, 0)
    now[0] += 10.0
    assert limiter.check("u1", limit=2, window_seconds=60) == (True, 0)
    allowed, retry_after = limiter.check("u1", limit=2, window_seconds=60)
    assert allowed is False
    assert retry_after == 50
    assert limiter.check("u2", limit=2, window_seconds=60) == (True, 0)

    now[0] += 51.0
    assert limiter.check("u1", limit=2, window_seconds=60) == (True, 0)


def test_chat_and_auth_rate_limits_return_429_with_retry_after(tmp_path: Path) -> None:
    db_path = tmp_path / "rate.db"
    load_raw_dir(RAW_DIR, db_path, embedder=None)
    settings = Settings(
        database_path=db_path,
        rate_limit_chat_per_minute=2,
        rate_limit_auth_per_minute=2,
    )
    container = AppContainer.build(db_path=db_path, model=_fake_model(), settings=settings)
    client = TestClient(create_app(container))

    admin_headers = _login_headers(client, "admin@admin.com", "admin123")
    user_headers = _login_headers(client, "user@user.com", "user123")

    blocked_login = client.post(
        "/api/auth/login",
        json={"email": "user@user.com", "password": "user123"},
    )
    assert blocked_login.status_code == 429
    assert int(blocked_login.headers["Retry-After"]) >= 1

    distinct_ip_login = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": "203.0.113.10"},
        json={"email": "user@user.com", "password": "user123"},
    )
    assert distinct_ip_login.status_code == 200

    first_chat = client.post("/api/chat", headers=user_headers, json={"message": "Oi 1"})
    second_chat = client.post("/api/chat", headers=user_headers, json={"message": "Oi 2"})
    assert first_chat.status_code == 200
    assert second_chat.status_code == 200
    blocked_chat = client.post("/api/chat", headers=user_headers, json={"message": "Oi 3"})
    assert blocked_chat.status_code == 429
    assert int(blocked_chat.headers["Retry-After"]) >= 1

    other_user_chat = client.post(
        "/api/chat",
        headers=admin_headers,
        json={"message": "Oi gestor"},
    )
    assert other_user_chat.status_code == 200
