from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)

from emporio.api import AppContainer, create_app
from emporio.etl.embeddings import l2_normalize
from emporio.etl.loader import load_raw_dir

RAW_DIR = Path("data/raw")


class _StubEmbedder:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [l2_normalize([1.0, float(i + 1)]) for i, _ in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return l2_normalize([1.0, 1.0])


def _parse_sse(raw_text: str) -> list[dict]:
    events: list[dict] = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


def _auth_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_list_tools_and_chat_sse_stream_persists_turn(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    embedder = _StubEmbedder()
    load_raw_dir(RAW_DIR, db_path, embedder=embedder)

    async def fake_stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaThinkingPart] | dict[int, DeltaToolCall]]:
        if len(messages) == 1:
            yield {0: DeltaThinkingPart(content="Consultando ficha do Takamine GD20.")}
            yield {
                1: DeltaToolCall(
                    name="get_product_details",
                    json_args='{"product_id_or_name": "Takamine GD20"}',
                )
            }
            return
        yield "O Takamine GD20 custa R$ 2.199,00 e sai por R$ 2.089,05 no PIX."

    container = AppContainer.build(
        db_path=db_path,
        embedder=embedder,
        model=FunctionModel(stream_function=fake_stream),
    )
    client = TestClient(create_app(container))
    admin_headers = _auth_headers(client, "admin@admin.com", "admin123")
    user_headers = _auth_headers(client, "user@user.com", "user123")

    tools_res = client.get("/api/tools", headers=admin_headers)
    assert tools_res.status_code == 200
    tool_ids = [t["tool_id"] for t in tools_res.json()["tools"]]
    assert len(tool_ids) == 5
    assert "lookup_order" in tool_ids

    res = client.post(
        "/api/chat",
        headers=user_headers,
        json={"message": "Quanto custa o Takamine GD20?"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(res.text)
    event_types = [e["type"] for e in events]
    assert event_types[0] == "session"
    assert "thinking_end" in event_types
    assert "tool_start" in event_types
    assert "tool_end" in event_types
    assert "text_delta" in event_types
    assert event_types[-1] == "done"

    session_id = events[0]["session_id"]
    session_res = client.get(f"/api/sessions/{session_id}", headers=user_headers)
    assert session_res.status_code == 200
    messages = session_res.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "2.089,05" in messages[1]["content"]


def test_chat_rejects_unknown_tools_and_streams_upstream_503_as_error_event(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "err.db"

    async def failing_stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        raise ModelHTTPError(
            status_code=503,
            model_name="google:gemini-4-hydrogen",
            body="overload",
        )
        yield ""

    container = AppContainer.build(
        db_path=db_path,
        embedder=None,
        model=FunctionModel(stream_function=failing_stream),
    )
    client = TestClient(create_app(container))
    admin_headers = _auth_headers(client, "admin@admin.com", "admin123")

    bad_tool = client.post(
        "/api/chat",
        headers=admin_headers,
        json={"message": "Oi", "enabled_tools": ["nonexistent_tool"]},
    )
    assert bad_tool.status_code == 400

    blank = client.post("/api/chat", headers=admin_headers, json={"message": "   "})
    assert blank.status_code == 422

    res = client.post("/api/chat", headers=admin_headers, json={"message": "Violões até 1000"})
    assert res.status_code == 200
    events = _parse_sse(res.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["status_code"] == 503
    assert "HTTP 503" in events[-1]["message"]
