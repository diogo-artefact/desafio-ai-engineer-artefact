from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from emporio.api import AppContainer, create_app
from emporio.config import Settings


def _fake_model() -> FunctionModel:
    def responder(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="ok")])

    async def streamer(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[Any]:
        yield "ok"

    return FunctionModel(responder, stream_function=streamer)


def test_openapi_schema_and_docs_are_exposed_with_tags_and_bearer_auth(tmp_path: Path) -> None:
    db_path = tmp_path / "openapi.db"
    settings = Settings(database_path=db_path)
    container = AppContainer.build(db_path=db_path, model=_fake_model(), settings=settings)
    client = TestClient(create_app(container))

    schema_res = client.get("/openapi.json")
    assert schema_res.status_code == 200
    spec = schema_res.json()

    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["title"] == "Empório da Música API"
    assert spec["info"]["version"] == "1.0.0"

    tag_names = {tag["name"] for tag in spec["tags"]}
    assert {
        "Sistema",
        "Autenticação",
        "Chat",
        "Conversas",
        "Pedidos",
        "Personalização e Memória",
        "Gestão (Admin)",
    }.issubset(tag_names)

    schemes = spec["components"]["securitySchemes"]
    assert "HTTPBearer" in schemes
    assert schemes["HTTPBearer"]["scheme"] == "bearer"

    assert "/api/chat" in spec["paths"]
    assert "/api/auth/login" in spec["paths"]
    assert "/api/orders/drafts/{draft_id}/confirm" in spec["paths"]
    assert "/api/knowledge/csvs" in spec["paths"]
    assert "security" in spec["paths"]["/api/chat"]["post"]
    assert "security" not in spec["paths"]["/api/health"]["get"]

    docs_res = client.get("/docs")
    assert docs_res.status_code == 200
    assert "swagger-ui" in docs_res.text.lower()
