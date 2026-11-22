from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)

from emporio.agent import (
    ALL_TOOL_IDS,
    AgentDeps,
    ConversationService,
    SupportAgent,
    TextDeltaEvent,
    ThinkingEndEvent,
    ToolEndEvent,
    ToolStartEvent,
    TurnDoneEvent,
)
from emporio.db.repository import SQLiteStoreRepository
from emporio.etl.embeddings import l2_normalize
from emporio.etl.loader import load_raw_dir

RAW_DIR = Path("data/raw")
CG_TZ = ZoneInfo("America/Campo_Grande")


class _StubEmbedder:
    def _encode(self, text: str) -> list[float]:
        lower = text.lower()
        return l2_normalize(
            [
                1.0 if "arrependimento" in lower or "desistir" in lower else 0.05,
                1.0 if "frete" in lower or "motoboy" in lower else 0.05,
                1.0 if "pix" in lower or "parcela" in lower else 0.05,
            ]
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text)


def _loaded_repo(tmp_path: Path) -> SQLiteStoreRepository:
    db_path = tmp_path / "emporio.db"
    embedder = _StubEmbedder()
    load_raw_dir(RAW_DIR, db_path, embedder=embedder)
    return SQLiteStoreRepository(db_path, embedder=embedder)


async def test_agent_streams_thinking_tool_calls_and_persists_session(tmp_path: Path) -> None:
    repo = _loaded_repo(tmp_path)
    tool_return_seen: list[dict] = []

    async def fake_stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaThinkingPart] | dict[int, DeltaToolCall]]:
        if len(messages) == 1:
            yield {0: DeltaThinkingPart(content="Vou consultar a ficha do Takamine GD20.")}
            yield {
                1: DeltaToolCall(
                    name="get_product_details",
                    json_args='{"product_id_or_name": "Takamine GD20"}',
                )
            }
            return
        for part in messages[-1].parts:
            if hasattr(part, "content") and isinstance(part.content, dict):
                tool_return_seen.append(part.content)
        yield "O Takamine GD20 custa R$ 2.199,00 e sai por R$ 2.089,05 no PIX."

    agent = SupportAgent(model=FunctionModel(stream_function=fake_stream))
    service = ConversationService(
        agent=agent,
        catalog=repo,
        orders=repo,
        policies=repo,
        knowledge=repo,
        sessions=repo,
    )

    events = [
        ev async for ev in service.stream_message("s-takamine", "Quanto custa o Takamine GD20?")
    ]
    assert any(isinstance(ev, ThinkingEndEvent) for ev in events)
    assert any(
        isinstance(ev, ToolStartEvent) and ev.tool_name == "get_product_details" for ev in events
    )
    assert any(isinstance(ev, ToolEndEvent) and "Takamine GD20" in ev.summary for ev in events)
    assert any(isinstance(ev, TextDeltaEvent) for ev in events)

    done = events[-1]
    assert isinstance(done, TurnDoneEvent)
    assert "2.089,05" in done.text
    assert tool_return_seen[0]["found"] is True
    assert tool_return_seen[0]["payment"]["pix_price_brl"] == 2089.05

    stored = repo.get_messages("s-takamine")
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert [step["type"] for step in stored[1]["trace"]] == ["thinking", "tool"]


async def test_disabling_tool_hides_it_from_model(tmp_path: Path) -> None:
    repo = _loaded_repo(tmp_path)
    exposed_names: list[str] = []

    async def fake_stream(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaThinkingPart]]:
        exposed_names.extend(t.name for t in info.function_tools)
        yield {0: DeltaThinkingPart(content="A ferramenta de pedidos está desativada.")}
        yield "A consulta de pedidos está desativada nos ajustes."

    agent = SupportAgent(model=FunctionModel(stream_function=fake_stream))
    deps = AgentDeps(
        catalog=repo,
        orders=repo,
        policies=repo,
        knowledge=repo,
        enabled_tools=ALL_TOOL_IDS - {"lookup_order"},
    )
    events = [ev async for ev in agent.stream_turn("Onde está meu pedido #7?", [], deps)]

    assert "lookup_order" not in exposed_names
    assert "search_catalog" in exposed_names
    assert any(isinstance(ev, ThinkingEndEvent) for ev in events)
    done = events[-1]
    assert isinstance(done, TurnDoneEvent)
    assert done.trace[0]["type"] == "thinking"


async def test_lgpd_order_tool_and_empty_base_guardrails(tmp_path: Path) -> None:
    empty_repo = SQLiteStoreRepository(tmp_path / "empty.db")
    empty_results: list[dict] = []

    async def call_catalog(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if len(messages) == 1:
            yield {
                0: DeltaToolCall(
                    name="search_catalog",
                    json_args='{"category": "Violões"}',
                )
            }
            return
        for p in messages[-1].parts:
            if hasattr(p, "content") and isinstance(p.content, dict):
                empty_results.append(p.content)
        yield "Envie os arquivos CSV primeiro."

    agent_empty = SupportAgent(model=FunctionModel(stream_function=call_catalog))
    deps_empty = AgentDeps(
        catalog=empty_repo,
        orders=empty_repo,
        policies=empty_repo,
        knowledge=empty_repo,
    )
    await agent_empty.reply("Quais violões têm?", [], deps_empty)
    assert empty_results[0]["error"] == "base_not_loaded"
    assert empty_results[0]["missing"] == "store_csvs"

    loaded_repo = _loaded_repo(tmp_path)
    order_results: list[dict] = []

    async def call_order(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if len(messages) == 1:
            yield {
                0: DeltaToolCall(
                    name="lookup_order",
                    json_args='{"order_id": 7, "contact": "errado@email.com"}',
                ),
                1: DeltaToolCall(
                    name="lookup_order",
                    json_args='{"order_id": 10, "contact": "bruno.martins@jmail.com"}',
                ),
            }
            return
        for p in messages[-1].parts:
            if hasattr(p, "content") and isinstance(p.content, dict):
                order_results.append(p.content)
        yield "Verificado."

    agent_order = SupportAgent(model=FunctionModel(stream_function=call_order))
    deps_loaded = AgentDeps(
        catalog=loaded_repo,
        orders=loaded_repo,
        policies=loaded_repo,
        knowledge=loaded_repo,
        reference_time=datetime(2026, 2, 20, 14, 0, tzinfo=CG_TZ),
    )
    done = await agent_order.reply("Verifique pedidos", [], deps_loaded)
    assert order_results[0]["verified"] is False
    assert order_results[1]["verified"] is True
    assert order_results[1]["order"]["order_id"] == 10
    assert done.trace[0]["summary"] == "Verificação LGPD não confirmada"
    assert done.trace[1]["summary"] == "Pedido #10 · confirmado"


async def test_simulate_tool_summary_formats_brl_and_not_found(tmp_path: Path) -> None:
    repo = _loaded_repo(tmp_path)

    async def call_sim(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if len(messages) == 1:
            yield {
                0: DeltaToolCall(
                    name="simulate_payment_and_shipping",
                    json_args='{"product_id_or_name": "Crafter HT-100", "city": "Campo Grande"}',
                ),
                1: DeltaToolCall(
                    name="simulate_payment_and_shipping",
                    json_args='{"product_id_or_name": "Inexistente XYZ"}',
                ),
            }
            return
        yield "Simulação concluída."

    agent = SupportAgent(model=FunctionModel(stream_function=call_sim))
    deps = AgentDeps(catalog=repo, orders=repo, policies=repo, knowledge=repo)
    done = await agent.reply("Simule", [], deps)
    assert done.trace[0]["summary"] == "PIX R$ 1.967,18 · até 12x"
    assert done.trace[1]["summary"] == "Produto não encontrado"
