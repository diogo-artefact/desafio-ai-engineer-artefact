from __future__ import annotations

import math
from typing import Protocol

from google import genai
from google.genai import types

from emporio.config import get_settings


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(math.fsum(x * x for x in vector))
    if norm == 0.0:
        return vector
    return [x / norm for x in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(math.fsum(x * x for x in a))
    norm_b = math.sqrt(math.fsum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        settings = get_settings()
        resolved_key = api_key if api_key is not None else settings.gemini_api_key
        if not resolved_key:
            raise ValueError("GEMINI_API_KEY não configurada para geração de embeddings.")
        self._client = genai.Client(api_key=resolved_key)
        self._model = model or settings.embedding_model
        self._dimensions = dimensions or settings.embedding_dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.models.embed_content(
            model=self._model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=self._dimensions,
            ),
        )
        return [l2_normalize(list(item.values)) for item in response.embeddings]

    def embed_query(self, text: str) -> list[float]:
        response = self._client.models.embed_content(
            model=self._model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=self._dimensions,
            ),
        )
        return l2_normalize(list(response.embeddings[0].values))


def get_default_embedder() -> GeminiEmbedder | None:
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    return GeminiEmbedder(
        api_key=settings.gemini_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
