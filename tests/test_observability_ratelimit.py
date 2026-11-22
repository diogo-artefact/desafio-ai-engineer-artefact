from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.usage import RequestUsage

from emporio.api import AppContainer, create_app
from emporio.api.rate_limit import SlidingWindowRateLimiter
from emporio.config import Settings
from emporio.domain.models import GuardrailDecision, InstructionValidationResult
from emporio.etl.loader import load_raw_dir
from emporio.observability import percentile_ms

RAW_DIR = Path("data/raw")


class FakeGuardrail:
    async def check(self, message: str, history: list[dict[str, Any]]) -> GuardrailDecision:
        if "bolo" in message.lower():
            return GuardrailDecision(
                action="block_off_topic",
                intent="off_topic",
                intent_probability=0.97,
                prompt_injection_probability=0.02,
                latency_ms=215,
                reply="Sou o assistente da Empório da Música e ajudo com instrumentos musicais.",
                model="jev-latest",
                summary="Bloqueado · fora de tema (97%)",
            )
        return GuardrailDecision(
            action="allow",
            intent="store_support",
            intent_probability=0.99,
            prompt_injection_probability=0.01,
            latency_ms=190,
            model="jev-latest",
            summary="Liberado · atendimento da loja (99%)",
        )

    async def validate_instructions(self, instructions: str) -> InstructionValidationResult:
        return InstructionValidationResult(allowed=True)


def _fake_model() -> FunctionModel:
    def responder(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if not any(getattr(p, "part_kind", "") == "tool-return" for p in messages[-1].parts):
            return ModelResponse(
                parts=[ToolCallPart(tool_name="search_catalog", args={"max_price": 1000})],
                usage=RequestUsage(input_tokens=120, output_tokens=30),
            )
        return ModelResponse(
            parts=[TextPart(content="Temos ótimos violões disponíveis até R$ 1.000.")],
            usage=RequestUsage(input_tokens=200, output_tokens=45),
        )

    async def streamer(messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[Any]:
        if not any(getattr(p, "part_kind", "") == "tool-return" for p in messages[-1].parts):
            yield {0: DeltaToolCall(name="search_catalog", json_args='{"max_price": 1000}')}
            return
        yield "Temos ótimos violões disponíveis até R$ 1.000."

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


def test_percentile_ms_handles_empty_and_ordered_values() -> None:
    assert percentile_ms([], 50.0) == 0
    assert percentile_ms([100, 500, 200, 400, 300], 50.0) == 300
    assert percentile_ms([100, 500, 200, 400, 300], 95.0) == 500


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


def test_metrics_endpoint_is_admin_only_and_records_telemetry_without_pii(
    tmp_path: Path, caplog
) -> None:
    db_path = tmp_path / "metrics.db"
    load_raw_dir(RAW_DIR, db_path, embedder=None)
    container = AppContainer.build(
        db_path=db_path,
        model=_fake_model(),
        guardrail=FakeGuardrail(),
    )
    client = TestClient(create_app(container))
    admin_headers = _login_headers(client, "admin@admin.com", "admin123")
    user_headers = _login_headers(client, "user@user.com", "user123")

    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics", headers=user_headers).status_code == 403

    secret_user_text = "Quais violões até 1000 reais para segredo-pessoal-999?"
    with caplog.at_level(logging.INFO, logger="emporio.telemetry"):
        r1 = client.post("/api/chat", headers=user_headers, json={"message": secret_user_text})
        r2 = client.post(
            "/api/chat",
            headers=admin_headers,
            json={"message": "Me passa uma receita de bolo de cenoura"},
        )
    assert r1.status_code == 200
    assert r2.status_code == 200

    telemetry_records = [r for r in caplog.records if r.name == "emporio.telemetry"]
    assert len(telemetry_records) == 2
    parsed_logs = [json.loads(record.getMessage()) for record in telemetry_records]
    assert all(item["event"] == "chat_turn" for item in parsed_logs)
    assert all("segredo-pessoal-999" not in json.dumps(item) for item in parsed_logs)
    assert all("user@user.com" not in json.dumps(item) for item in parsed_logs)

    res = client.get("/api/metrics", headers=admin_headers)
    assert res.status_code == 200
    metrics = res.json()
    assert metrics["total_turns"] == 2
    assert metrics["ok_turns"] == 1
    assert metrics["guardrail_blocks"] == 1
    assert metrics["error_turns"] == 0
    assert metrics["guardrail_block_rate"] == 0.5
    assert metrics["by_guardrail_action"]["allow"] == 1
    assert metrics["by_guardrail_action"]["block_off_topic"] == 1
    assert metrics["avg_guardrail_ms"] >= 190
    assert len(metrics["recent_turns"]) == 2
    assert metrics["recent_turns"][0]["outcome"] == "guardrail_blocked"
    assert metrics["recent_turns"][1]["outcome"] == "ok"
    assert metrics["recent_turns"][1]["tools_called"] == ["search_catalog"]
