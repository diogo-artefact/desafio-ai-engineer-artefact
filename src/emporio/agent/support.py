from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModelSettings

from emporio.agent.events import (
    ALL_TOOL_IDS,
    ALLOWED_MODEL_IDS,
    DEFAULT_MODEL_ID,
    TOOL_META_BY_ID,
    AgentEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolEndEvent,
    ToolStartEvent,
    TurnDoneEvent,
)
from emporio.agent.tools import AgentDeps, register_tools
from emporio.config import get_settings
from emporio.ports import (
    CatalogRepository,
    KnowledgeRepository,
    OrderRepository,
    PolicyRetriever,
    SessionRepository,
    SettingsRepository,
)

SYSTEM_PROMPT = (
    "Você é o assistente virtual da Empório da Música, loja especializada em instrumentos "
    "musicais em Campo Grande (MS).\n\n"
    "Diretrizes obrigatórias:\n"
    "1. Tom de voz: informal mas profissional, acolhedor e objetivo, como um amigo que entende "
    "de música. Evite linguagem robotizada e não use emojis.\n"
    "2. Escopo estrito: a loja vende exclusivamente instrumentos musicais. Não vendemos "
    "acessórios como cordas avulsas, palhetas, cabos, cases, pedais ou amplificadores. Quando "
    "pedirem acessórios, informe isso com clareza e sugira lojas parceiras ou especializadas.\n"
    "3. Fatos verificados: nunca invente preços, estoques, especificações, promoções, prazos ou "
    "dados de pedido. Sempre consulte as ferramentas disponíveis antes de responder. Se uma "
    "ferramenta estiver desativada ou a base ainda não tiver sido carregada, diga claramente que "
    "essa consulta está indisponível no momento.\n"
    "4. Estoque e status: se um produto estiver esgotado ou descontinuado, informe com "
    "transparência e ofereça alternativas semelhantes disponíveis retornadas pelas ferramentas. "
    "Nunca ofereça item coming_soon para entrega imediata.\n"
    "5. Promoções e PIX: quando houver promoção ativa, apresente o preço original, o percentual "
    "de desconto e o preço promocional. O desconto de 5% no PIX nunca acumula com promoções "
    "ativas. Se o cliente perguntar sobre uma promoção expirada, informe com transparência que "
    "ela não está mais vigente e mostre o preço atual.\n"
    "6. Privacidade (LGPD): nunca informe dados de pedido sem confirmar número do pedido junto "
    "com o e-mail ou telefone cadastrado usando lookup_order.\n"
    "7. Contatos e expediente: ao informar telefone/WhatsApp, priorize (67) 3341-4444 (capa e "
    "ficha cadastral) e mencione também (67) 3321-4500 (seção de atendimento do manual). Use o "
    "e-mail contato@emporiodamusica.com.br. Fora do expediente, informe o horário de retorno.\n"
    "8. Formatação: responda em português do Brasil, de forma limpa e direta. Use tabelas curtas "
    "em Markdown quando comparar preços ou condições de pagamento."
)


def _history_to_messages(history: list[dict[str, Any]]) -> list[ModelMessage]:
    converted: list[ModelMessage] = []
    for item in history:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "user":
            converted.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role == "assistant":
            converted.append(ModelResponse(parts=[TextPart(content=content)]))
    return converted


ORDER_STATUS_PT: dict[str, str] = {
    "pending": "pendente",
    "confirmed": "confirmado",
    "shipped": "enviado",
    "delivered": "entregue",
    "cancelled": "cancelado",
}


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _summarize_tool_result(tool_name: str, result: Any) -> str:
    if isinstance(result, dict):
        if result.get("error") == "base_not_loaded":
            return "Base ainda não carregada"
        if tool_name == "search_catalog":
            return f"{result.get('count', 0)} instrumento(s) encontrado(s)"
        if tool_name == "get_product_details":
            if not result.get("found"):
                return "Produto não encontrado"
            prod = result.get("product", {})
            return f"{prod.get('name', 'Produto')} · estoque {prod.get('stock_quantity', 0)}"
        if tool_name == "simulate_payment_and_shipping":
            if result.get("found") is False:
                return "Produto não encontrado"
            payment = result.get("payment", {})
            if payment:
                pix_val = float(payment.get("pix_price_brl", 0))
                max_x = payment.get("max_installments", 1)
                return f"PIX {_format_brl(pix_val)} · até {max_x}x"
        if tool_name == "lookup_order":
            if not result.get("verified"):
                return "Verificação LGPD não confirmada"
            order = result.get("order", {})
            raw_status = str(order.get("status", ""))
            status_pt = ORDER_STATUS_PT.get(raw_status, raw_status)
            return f"Pedido #{order.get('order_id')} · {status_pt}"
        if tool_name == "search_store_policies":
            chunks = result.get("chunks", [])
            return f"{len(chunks)} trecho(s) do manual recuperado(s)"
    return "Consulta concluída"


def _tool_args_dict(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            return parsed if isinstance(parsed, dict) else {"raw": raw_args}
        except json.JSONDecodeError:
            return {"raw": raw_args}
    return {}


def _format_tool_label(tool_name: str, args: dict[str, Any], *, done: bool) -> str:
    meta = TOOL_META_BY_ID.get(tool_name)
    base = (meta.done_label if done else meta.running_label) if meta else tool_name
    hint = (
        args.get("product_id_or_name")
        or args.get("category")
        or args.get("query")
        or (f"#{args['order_id']}" if "order_id" in args else None)
    )
    if hint:
        short = str(hint).strip()
        if len(short) > 48:
            short = short[:45] + "..."
        return f"{base} · {short}"
    return base


class SupportAgent:
    def __init__(self, model: str | Model | None = None) -> None:
        settings = get_settings()
        if settings.gemini_api_key and not os.environ.get("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key

        self._model = model if model is not None else settings.llm_model
        self._agent: Agent[AgentDeps, str] = Agent(
            self._model,
            deps_type=AgentDeps,
            instructions=SYSTEM_PROMPT,
        )
        register_tools(self._agent)

    @property
    def allows_runtime_model_override(self) -> bool:
        return isinstance(self._model, str)

    async def stream_turn(
        self,
        message: str,
        history: list[dict[str, Any]],
        deps: AgentDeps,
        model_override: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        active_model: str | Model = (
            model_override
            if model_override is not None and self.allows_runtime_model_override
            else self._model
        )
        is_google = isinstance(active_model, str) and active_model.startswith("google:")
        model_settings = (
            GoogleModelSettings(
                thinking="low",
                google_thinking_config={"include_thoughts": True},
            )
            if is_google
            else None
        )
        message_history = _history_to_messages(history)
        trace: list[dict[str, Any]] = []
        full_text_parts: list[str] = []
        thinking_started_at: float | None = None
        thinking_chunks: list[str] = []
        tool_timers: dict[str, tuple[str, dict[str, Any], float]] = {}

        async with self._agent.iter(
            message,
            deps=deps,
            message_history=message_history,
            model=active_model if active_model != self._model else None,
            model_settings=model_settings,
        ) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    async with node.stream(run.ctx) as stream:
                        async for event in stream:
                            if isinstance(event, PartStartEvent):
                                if isinstance(event.part, ThinkingPart):
                                    thinking_started_at = time.perf_counter()
                                    thinking_chunks = []
                                    yield ThinkingStartEvent()
                                    if event.part.content:
                                        thinking_chunks.append(event.part.content)
                                        yield ThinkingDeltaEvent(delta=event.part.content)
                                elif isinstance(event.part, TextPart) and event.part.content:
                                    full_text_parts.append(event.part.content)
                                    yield TextDeltaEvent(delta=event.part.content)
                            elif isinstance(event, PartDeltaEvent):
                                if isinstance(event.delta, ThinkingPartDelta):
                                    delta = event.delta.content_delta or ""
                                    if delta:
                                        thinking_chunks.append(delta)
                                        yield ThinkingDeltaEvent(delta=delta)
                                elif isinstance(event.delta, TextPartDelta):
                                    delta = event.delta.content_delta or ""
                                    if delta:
                                        full_text_parts.append(delta)
                                        yield TextDeltaEvent(delta=delta)
                            elif isinstance(event, PartEndEvent) and isinstance(
                                event.part, ThinkingPart
                            ):
                                elapsed_ms = (
                                    int((time.perf_counter() - thinking_started_at) * 1000)
                                    if thinking_started_at is not None
                                    else 0
                                )
                                content = "".join(thinking_chunks).strip() or event.part.content
                                trace.append(
                                    {
                                        "type": "thinking",
                                        "label": "Pensou",
                                        "duration_ms": elapsed_ms,
                                        "content": content,
                                    }
                                )
                                yield ThinkingEndEvent(duration_ms=elapsed_ms, content=content)
                                thinking_started_at = None
                                thinking_chunks = []

                    if thinking_started_at is not None:
                        elapsed_ms = int((time.perf_counter() - thinking_started_at) * 1000)
                        content = "".join(thinking_chunks).strip()
                        trace.append(
                            {
                                "type": "thinking",
                                "label": "Pensou",
                                "duration_ms": elapsed_ms,
                                "content": content,
                            }
                        )
                        yield ThinkingEndEvent(duration_ms=elapsed_ms, content=content)
                        thinking_started_at = None
                        thinking_chunks = []

                elif Agent.is_call_tools_node(node):
                    async with node.stream(run.ctx) as tool_stream:
                        async for event in tool_stream:
                            if isinstance(event, FunctionToolCallEvent):
                                call_id = event.part.tool_call_id
                                name = event.part.tool_name
                                args = _tool_args_dict(event.part.args)
                                tool_timers[call_id] = (name, args, time.perf_counter())
                                yield ToolStartEvent(
                                    tool_call_id=call_id,
                                    tool_name=name,
                                    label=_format_tool_label(name, args, done=False),
                                    args=args,
                                )
                            elif isinstance(event, FunctionToolResultEvent):
                                call_id = event.tool_call_id
                                name, args, started = tool_timers.pop(
                                    call_id, (event.part.tool_name, {}, time.perf_counter())
                                )
                                elapsed_ms = int((time.perf_counter() - started) * 1000)
                                label = _format_tool_label(name, args, done=True)
                                summary = _summarize_tool_result(name, event.part.content)
                                trace.append(
                                    {
                                        "type": "tool",
                                        "tool_name": name,
                                        "label": label,
                                        "summary": summary,
                                        "args": args,
                                        "duration_ms": elapsed_ms,
                                    }
                                )
                                yield ToolEndEvent(
                                    tool_call_id=call_id,
                                    tool_name=name,
                                    label=label,
                                    summary=summary,
                                    duration_ms=elapsed_ms,
                                )

        final_text = "".join(full_text_parts).strip()
        if not final_text and run.result is not None and isinstance(run.result.output, str):
            final_text = run.result.output.strip()
        yield TurnDoneEvent(text=final_text, trace=trace)

    async def reply(
        self,
        message: str,
        history: list[dict[str, Any]],
        deps: AgentDeps,
    ) -> TurnDoneEvent:
        done: TurnDoneEvent | None = None
        async for event in self.stream_turn(message, history, deps):
            if isinstance(event, TurnDoneEvent):
                done = event
        return done or TurnDoneEvent(text="", trace=[])


def _session_title_from(message: str) -> str:
    clean = " ".join(message.strip().split())
    if len(clean) <= 44:
        return clean or "Nova conversa"
    return clean[:41].rstrip() + "..."


class ConversationService:
    def __init__(
        self,
        agent: SupportAgent,
        catalog: CatalogRepository,
        orders: OrderRepository,
        policies: PolicyRetriever,
        knowledge: KnowledgeRepository,
        sessions: SessionRepository,
        settings_repo: SettingsRepository | None = None,
        default_model: str = DEFAULT_MODEL_ID,
    ) -> None:
        self._agent = agent
        self._catalog = catalog
        self._orders = orders
        self._policies = policies
        self._knowledge = knowledge
        self._sessions = sessions
        self._settings = settings_repo
        self._default_model = (
            default_model if default_model in ALLOWED_MODEL_IDS else DEFAULT_MODEL_ID
        )

    def resolve_active_model(self) -> str:
        if self._settings is not None:
            saved = self._settings.get_setting("active_model")
            if saved in ALLOWED_MODEL_IDS:
                return saved
        return self._default_model

    def _ensure_session(
        self,
        session_id: str,
        first_message: str,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        existing = self._sessions.get_session(session_id, user_id=user_id)
        if existing is None:
            self._sessions.create_session(
                session_id, _session_title_from(first_message), user_id=user_id
            )
            return []
        history = self._sessions.get_messages(session_id)
        if not history:
            self._sessions.update_session_title(session_id, _session_title_from(first_message))
        return history

    async def stream_message(
        self,
        session_id: str,
        message: str,
        enabled_tools: frozenset[str] | None = None,
        user_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        history = self._ensure_session(session_id, message, user_id=user_id)
        self._sessions.append_message(session_id, "user", message)

        deps = AgentDeps(
            catalog=self._catalog,
            orders=self._orders,
            policies=self._policies,
            knowledge=self._knowledge,
            enabled_tools=enabled_tools if enabled_tools is not None else ALL_TOOL_IDS,
        )
        model_override = (
            self.resolve_active_model() if self._agent.allows_runtime_model_override else None
        )
        async for event in self._agent.stream_turn(
            message, history, deps, model_override=model_override
        ):
            if isinstance(event, TurnDoneEvent):
                self._sessions.append_message(
                    session_id, "assistant", event.text, trace=event.trace
                )
            yield event

    async def send_message(
        self,
        session_id: str,
        message: str,
        enabled_tools: frozenset[str] | None = None,
        user_id: str | None = None,
    ) -> TurnDoneEvent:
        done: TurnDoneEvent | None = None
        async for event in self.stream_message(
            session_id,
            message,
            enabled_tools=enabled_tools,
            user_id=user_id,
        ):
            if isinstance(event, TurnDoneEvent):
                done = event
        return done or TurnDoneEvent(text="", trace=[])
