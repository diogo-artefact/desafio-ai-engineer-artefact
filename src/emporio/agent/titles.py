from __future__ import annotations

import asyncio
import logging
import os

import httpx
from google.genai import errors as genai_errors
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModelSettings

from emporio.config import Settings, get_settings

logger = logging.getLogger(__name__)

TITLE_INSTRUCTIONS = (
    "Gere um título curto em português do Brasil (3 a 6 palavras, máximo 44 caracteres) "
    "resumindo a primeira pergunta do cliente em uma loja de instrumentos musicais. "
    "Retorne apenas o título, sem aspas, sem ponto final, sem markdown e sem emojis."
)


def clean_generated_title(raw: str, max_len: int = 44) -> str | None:
    first_line = raw.strip().splitlines()[0] if raw.strip() else ""
    cleaned = first_line.strip().strip("\"'`*#-_").rstrip(".").strip()
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return None
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


class GeminiTitleGenerator:
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
        self._agent: Agent[None, str] = Agent(
            resolved,
            instructions=TITLE_INSTRUCTIONS,
        )

    async def generate(self, message: str) -> str | None:
        clean_input = message.strip()
        if not clean_input:
            return None
        model_settings = GoogleModelSettings(thinking="minimal") if self._is_google else None
        try:
            result = await asyncio.wait_for(
                self._agent.run(clean_input, model_settings=model_settings),
                timeout=self._timeout,
            )
            return clean_generated_title(str(result.output))
        except (
            TimeoutError,
            ModelHTTPError,
            ModelAPIError,
            UnexpectedModelBehavior,
            genai_errors.APIError,
            httpx.HTTPError,
            OSError,
        ) as exc:
            logger.warning("Falha ao gerar título paralelo da conversa: %s", exc)
            return None


def get_default_title_generator(settings: Settings | None = None) -> GeminiTitleGenerator | None:
    resolved = settings or get_settings()
    if not resolved.gemini_api_key.strip() and not os.environ.get("GEMINI_API_KEY"):
        return None
    return GeminiTitleGenerator(model=resolved.llm_model)
