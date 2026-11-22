from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

import httpx
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModelSettings

from emporio.config import Settings, get_settings
from emporio.domain.models import UserMemory
from emporio.domain.text import normalize_text

logger = logging.getLogger(__name__)

ALLOWED_MEMORY_KEYS: frozenset[str] = frozenset(
    {
        "instrumento_interesse",
        "nivel_musical",
        "cidade_entrega",
        "preferencia_pagamento",
        "preferencia_cordas",
        "orcamento",
        "estilo_musical",
        "preferencia_marca",
    }
)

LONG_DIGITS_RE = re.compile(r"\d{8,}")
TRACKING_RE = re.compile(r"\bBR[A-Z0-9]{6,}BR\b", flags=re.IGNORECASE)
FORBIDDEN_MEMORY_TERMS: tuple[str, ...] = (
    "@",
    "pedido",
    "rastreio",
    "cpf",
    "senha",
    "ajustes",
    "base de dados",
    "csv",
    "pdf",
)

COMPACTION_INSTRUCTIONS = (
    "Você compacta mensagens antigas de uma conversa de atendimento da loja de instrumentos "
    "musicais Empório da Música em um resumo factual conciso em português do Brasil.\n\n"
    "Regras obrigatórias:\n"
    "1. Preserve TODAS as preferências e restrições explícitas do cliente (forma de pagamento "
    "preferida, cidade de entrega, orçamento, tipo de cordas, instrumento de interesse, nível "
    "musical).\n"
    "2. Preserve modelos consultados, modelos descartados e decisões já tomadas.\n"
    "3. Nunca inclua dados pessoais sensíveis completos (e-mail, telefone ou endereço residencial) "
    "nem declare que um pedido está pré-autorizado para consulta futura sem verificação.\n"
    "4. Use até 8 tópicos curtos e objetivos."
)

MEMORY_EXTRACTION_INSTRUCTIONS = (
    "Extraia apenas preferências duráveis e não sensíveis declaradas explicitamente pelo cliente "
    "em uma loja de instrumentos musicais.\n\n"
    "Chaves permitidas:\n"
    "- instrumento_interesse\n"
    "- nivel_musical\n"
    "- cidade_entrega\n"
    "- preferencia_pagamento\n"
    "- preferencia_cordas\n"
    "- orcamento\n"
    "- estilo_musical\n"
    "- preferencia_marca\n\n"
    "Regras obrigatórias:\n"
    "1. Só extraia fatos que o cliente afirmou claramente sobre si mesmo.\n"
    "2. Retorne lista vazia se a mensagem for apenas uma consulta pontual sem preferência "
    "pessoal.\n"
    "3. Nunca extraia e-mail, telefone, CPF, número de pedido, código de rastreio ou dados de "
    "terceiros."
)


class ExtractedFact(BaseModel):
    fact_key: str
    content: str


class ExtractedMemories(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)


def filter_safe_memories(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    accepted: dict[str, str] = {}
    for raw_key, raw_content in items:
        key = raw_key.strip().lower()
        content = " ".join(raw_content.strip().split())
        if key not in ALLOWED_MEMORY_KEYS or not content:
            continue
        if len(content) > 140:
            content = content[:137].rstrip() + "..."
        lower = content.lower()
        norm = normalize_text(content)
        digits_only = re.sub(r"\D", "", content)
        if any(term in lower or term in norm for term in FORBIDDEN_MEMORY_TERMS):
            continue
        if LONG_DIGITS_RE.search(digits_only) or TRACKING_RE.search(content):
            continue
        accepted[key] = content
    return list(accepted.items())


class GeminiConversationCompactor:
    def __init__(
        self,
        model: str | Model | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        settings = get_settings()
        if settings.gemini_api_key and not os.environ.get("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        resolved = model if model is not None else settings.llm_model
        self._is_google = isinstance(resolved, str) and resolved.startswith("google:")
        self._timeout = timeout_seconds
        self._agent: Agent[None, str] = Agent(
            resolved,
            instructions=COMPACTION_INSTRUCTIONS,
        )

    async def compact(
        self,
        previous_summary: str | None,
        messages: list[dict[str, Any]],
    ) -> str | None:
        if not messages:
            return previous_summary
        transcript = "\n".join(
            f"{'Cliente' if m.get('role') == 'user' else 'Assistente'}: "
            f"{str(m.get('content', '')).strip()}"
            for m in messages
            if str(m.get("content", "")).strip()
        )
        if not transcript:
            return previous_summary
        prompt_parts = []
        if previous_summary:
            prompt_parts.append(f"Resumo anterior:\n{previous_summary}")
        prompt_parts.append(f"Novas mensagens a incorporar no resumo:\n{transcript}")
        prompt = "\n\n".join(prompt_parts)
        model_settings = GoogleModelSettings(thinking="minimal") if self._is_google else None
        try:
            result = await asyncio.wait_for(
                self._agent.run(prompt, model_settings=model_settings),
                timeout=self._timeout,
            )
            cleaned = str(result.output).strip()
            return cleaned or previous_summary
        except (
            TimeoutError,
            ModelHTTPError,
            ModelAPIError,
            UnexpectedModelBehavior,
            genai_errors.APIError,
            httpx.HTTPError,
            OSError,
        ) as exc:
            logger.warning("Falha na compactação da conversa: %s", exc)
            return None


class GeminiUserMemoryExtractor:
    def __init__(
        self,
        model: str | Model | None = None,
        *,
        timeout_seconds: float = 8.0,
    ) -> None:
        settings = get_settings()
        if settings.gemini_api_key and not os.environ.get("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        resolved = model if model is not None else settings.llm_model
        self._is_google = isinstance(resolved, str) and resolved.startswith("google:")
        self._timeout = timeout_seconds
        self._agent: Agent[None, ExtractedMemories] = Agent(
            resolved,
            output_type=ExtractedMemories,
            instructions=MEMORY_EXTRACTION_INSTRUCTIONS,
        )

    async def extract(
        self,
        user_message: str,
        assistant_response: str,
        existing: list[UserMemory],
    ) -> list[tuple[str, str]]:
        clean_user = user_message.strip()
        if not clean_user:
            return []
        existing_block = (
            "\n".join(f"- {m.fact_key}: {m.content}" for m in existing)
            if existing
            else "(nenhuma)"
        )
        prompt = (
            f"Memórias já salvas:\n{existing_block}\n\n"
            f"Mensagem do cliente:\n{clean_user}\n\n"
            f"Resposta do assistente:\n{assistant_response.strip()[:500]}"
        )
        model_settings = GoogleModelSettings(thinking="minimal") if self._is_google else None
        try:
            result = await asyncio.wait_for(
                self._agent.run(prompt, model_settings=model_settings),
                timeout=self._timeout,
            )
            raw_pairs = [(f.fact_key, f.content) for f in result.output.facts]
            return filter_safe_memories(raw_pairs)
        except (
            TimeoutError,
            ModelHTTPError,
            ModelAPIError,
            UnexpectedModelBehavior,
            genai_errors.APIError,
            httpx.HTTPError,
            OSError,
        ) as exc:
            logger.warning("Falha na extração de memória do usuário: %s", exc)
            return []


def get_default_compactor(
    settings: Settings | None = None,
) -> GeminiConversationCompactor | None:
    resolved = settings or get_settings()
    if not resolved.gemini_api_key.strip() and not os.environ.get("GEMINI_API_KEY"):
        return None
    return GeminiConversationCompactor(model=resolved.llm_model)


def get_default_memory_extractor(
    settings: Settings | None = None,
) -> GeminiUserMemoryExtractor | None:
    resolved = settings or get_settings()
    if not resolved.gemini_api_key.strip() and not os.environ.get("GEMINI_API_KEY"):
        return None
    return GeminiUserMemoryExtractor(model=resolved.llm_model)
