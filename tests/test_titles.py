from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from emporio.agent import (
    ConversationService,
    GeminiTitleGenerator,
    SessionTitleEvent,
    SupportAgent,
    TurnDoneEvent,
    clean_generated_title,
)
from emporio.api import AppContainer, create_app
from emporio.db.repository import SQLiteStoreRepository
from emporio.etl.loader import load_raw_dir


class _DelayedTitleGenerator:
    def __init__(self, title: str | None, delay_seconds: float = 0.05) -> None:
        self._title = title
        self._delay = delay_seconds
        self.calls: list[str] = []

    async def generate(self, message: str) -> str | None:
        self.calls.append(message)
        await asyncio.sleep(self._delay)
        return self._title


class _FailingTitleGenerator:
    async def generate(self, message: str) -> str | None:
        raise RuntimeError("title failure")


def test_clean_generated_title_strips_noise_and_caps_length() -> None:
    assert clean_generated_title(' "Violões até R$ 1.000." \n segunda linha') == (
        "Violões até R$ 1.000"
    )
    long_title = "Título muito longo que ultrapassa o limite máximo permitido na barra lateral"
    cleaned = clean_generated_title(long_title)
    assert cleaned is not None and len(cleaned) == 44 and cleaned.endswith("...")
    assert clean_generated_title("   ") is None


async def test_parallel_title_generation_overlaps_agent_and_runs_only_once(
    tmp_path: Path,
) -> None:
    repo = SQLiteStoreRepository(tmp_path / "titles.db")

    async def slow_agent(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str]:
        await asyncio.sleep(0.15)
        yield "Temos 12 violões disponíveis até R$ 1.000."

    generator = _DelayedTitleGenerator("Violões até R$ 1.000", delay_seconds=0.12)
    service = ConversationService(
        agent=SupportAgent(model=FunctionModel(stream_function=slow_agent)),
        catalog=repo,
        orders=repo,
        policies=repo,
        knowledge=repo,
        sessions=repo,
        title_generator=generator,
    )

    started = time.perf_counter()
    first_events = [
        ev
        async for ev in service.stream_message(
            "s-parallel",
            "Oi, quais opções de violões disponíveis vocês têm custando até mil reais?",
        )
    ]
    elapsed = time.perf_counter() - started

    assert elapsed < 0.24
    title_events = [ev for ev in first_events if isinstance(ev, SessionTitleEvent)]
    assert len(title_events) == 1
    assert title_events[0].title == "Violões até R$ 1.000"
    assert any(isinstance(ev, TurnDoneEvent) for ev in first_events)
    session = repo.get_session("s-parallel")
    assert session is not None and session["title"] == "Violões até R$ 1.000"

    second_events = [
        ev async for ev in service.stream_message("s-parallel", "E qual o mais barato?")
    ]
    assert not any(isinstance(ev, SessionTitleEvent) for ev in second_events)
    assert len(generator.calls) == 1


async def test_title_generator_failure_keeps_fallback_title(tmp_path: Path) -> None:
    repo = SQLiteStoreRepository(tmp_path / "fallback.db")

    async def fast_agent(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str]:
        yield "Resposta normal."

    service = ConversationService(
        agent=SupportAgent(model=FunctionModel(stream_function=fast_agent)),
        catalog=repo,
        orders=repo,
        policies=repo,
        knowledge=repo,
        sessions=repo,
        title_generator=_FailingTitleGenerator(),
    )

    done = await service.send_message("s-fail", "Quero saber sobre garantia")
    assert done.text == "Resposta normal."
    session = repo.get_session("s-fail")
    assert session is not None and session["title"] == "Quero saber sobre garantia"


def test_api_streams_session_title_event_and_persists(tmp_path: Path) -> None:
    db_path = tmp_path / "api_titles.db"
    load_raw_dir(Path("data/raw"), db_path, embedder=None)

    async def fake_agent(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str]:
        yield "O Takamine GD20 custa R$ 2.199,00."

    title_gen = GeminiTitleGenerator(model=TestModel(custom_output_text="Takamine GD20 no PIX"))
    container = AppContainer.build(
        db_path=db_path,
        embedder=None,
        model=FunctionModel(stream_function=fake_agent),
        title_generator=title_gen,
    )
    client = TestClient(create_app(container))
    token = client.post(
        "/api/auth/login",
        json={"email": "user@user.com", "password": "user123"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/api/chat",
        headers=headers,
        json={"message": "Quanto custa o violão Takamine GD20 pagando à vista no PIX?"},
    )
    assert res.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in res.text.splitlines()
        if line.startswith("data: ")
    ]
    title_ev = next((ev for ev in events if ev["type"] == "session_title"), None)
    assert title_ev is not None
    assert title_ev["title"] == "Takamine GD20 no PIX"

    sid = events[0]["session_id"]
    session_res = client.get(f"/api/sessions/{sid}", headers=headers)
    assert session_res.status_code == 200
    assert session_res.json()["session"]["title"] == "Takamine GD20 no PIX"
