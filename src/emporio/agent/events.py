from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class ToolMeta:
    tool_id: str
    label: str
    description: str
    running_label: str
    done_label: str


TOOL_REGISTRY: tuple[ToolMeta, ...] = (
    ToolMeta(
        tool_id="search_catalog",
        label="Busca no catálogo",
        description="Filtra instrumentos disponíveis, categorias, preços e promoções",
        running_label="Consultando catálogo",
        done_label="Consultou catálogo",
    ),
    ToolMeta(
        tool_id="get_product_details",
        label="Detalhes do produto",
        description="Consulta ficha completa, estoque, preço no PIX e alternativas",
        running_label="Consultando ficha do produto",
        done_label="Consultou ficha do produto",
    ),
    ToolMeta(
        tool_id="simulate_payment_and_shipping",
        label="Pagamento e frete",
        description="Simula parcelamento sem juros, regra de PIX e frete por cidade",
        running_label="Simulando pagamento e frete",
        done_label="Simulou pagamento e frete",
    ),
    ToolMeta(
        tool_id="lookup_order",
        label="Consulta de pedidos (LGPD)",
        description="Verifica status, rastreamento e elegibilidade de devolução em 2 fatores",
        running_label="Verificando pedido (LGPD)",
        done_label="Verificou pedido (LGPD)",
    ),
    ToolMeta(
        tool_id="search_store_policies",
        label="Manual de políticas",
        description="Consulta regras de troca, garantia, expediente e privacidade",
        running_label="Consultando manual de políticas",
        done_label="Consultou manual de políticas",
    ),
)

TOOL_META_BY_ID: dict[str, ToolMeta] = {meta.tool_id: meta for meta in TOOL_REGISTRY}
ALL_TOOL_IDS: frozenset[str] = frozenset(TOOL_META_BY_ID)


class ThinkingStartEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["thinking_start"] = "thinking_start"


class ThinkingDeltaEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["thinking_delta"] = "thinking_delta"
    delta: str


class ThinkingEndEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["thinking_end"] = "thinking_end"
    duration_ms: int
    content: str


class ToolStartEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["tool_start"] = "tool_start"
    tool_call_id: str
    tool_name: str
    label: str
    args: dict[str, Any]


class ToolEndEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["tool_end"] = "tool_end"
    tool_call_id: str
    tool_name: str
    label: str
    summary: str
    duration_ms: int


class TextDeltaEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["text_delta"] = "text_delta"
    delta: str


class TurnDoneEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal["done"] = "done"
    text: str
    trace: list[dict[str, Any]]


AgentEvent = (
    ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | ToolStartEvent
    | ToolEndEvent
    | TextDeltaEvent
    | TurnDoneEvent
)
