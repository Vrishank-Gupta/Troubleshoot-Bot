"""Embedding generation via OpenAI-compatible API."""
from __future__ import annotations

import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_client() -> AsyncOpenAI:
    s = get_settings()
    return AsyncOpenAI(
        api_key=s.openai_api_key,
        base_url=s.openai_api_base,
        timeout=s.llm_timeout,
    )


async def embed_text(text: str) -> list[float]:
    """Return embedding vector for a single text."""
    s = get_settings()
    client = _get_client()
    text = text.replace("\n", " ").strip()[:8000]
    if not text:
        return [0.0] * s.embedding_dimensions
    resp = await client.embeddings.create(
        model=s.embedding_model,
        input=text,
        dimensions=s.embedding_dimensions,
    )
    return resp.data[0].embedding


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Return embeddings for a batch of texts."""
    if not texts:
        return []
    s = get_settings()
    client = _get_client()
    cleaned = [t.replace("\n", " ").strip()[:8000] for t in texts]
    resp = await client.embeddings.create(
        model=s.embedding_model,
        input=cleaned,
        dimensions=s.embedding_dimensions,
    )
    return [item.embedding for item in sorted(resp.data, key=lambda x: x.index)]
