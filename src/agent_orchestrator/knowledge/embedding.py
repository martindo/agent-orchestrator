"""EmbeddingService — OpenAI-compatible embedding API client.

Provides async embedding generation and cosine similarity computation
for semantic search in the knowledge store.

Thread-safe: Uses an internal lock for shared state.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in range [-1, 1], or 0.0 if either vector
        is zero-length or vectors have different dimensions.
    """
    if len(a) != len(b) or len(a) == 0:
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


class EmbeddingService:
    """Async client for OpenAI-compatible embedding APIs.

    Thread-safe: Uses an internal lock for the httpx client lifecycle.

    Args:
        api_key: API key for authentication.
        model: Embedding model name.
        base_url: Base URL for the API (must include /v1 suffix).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._lock = threading.Lock()
        self._client: Any | None = None
        logger.debug(
            "EmbeddingService initialized (model=%s, base_url=%s)",
            model,
            self._base_url,
        )

    def _get_client(self) -> Any:
        """Lazily create and return the httpx async client."""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    import httpx

                    self._client = httpx.AsyncClient(
                        base_url=self._base_url,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        timeout=30.0,
                    )
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string.

        Args:
            text: The text to embed.

        Returns:
            Embedding vector as a list of floats, or empty list on failure.
        """
        if not text.strip():
            return []

        try:
            client = self._get_client()
            response = await client.post(
                "/embeddings",
                json={"input": text, "model": self._model},
            )
            response.raise_for_status()
            data = response.json()
            embedding = data["data"][0]["embedding"]
            return list(embedding)
        except Exception as exc:
            logger.error(
                "Failed to embed text (len=%d): %s", len(text), exc, exc_info=True,
            )
            return []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single API call.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors (one per input text). Returns a list
            of empty lists on failure.
        """
        if not texts:
            return []

        # Filter out empty strings but track indices
        non_empty_indices: list[int] = []
        non_empty_texts: list[str] = []
        for i, t in enumerate(texts):
            if t.strip():
                non_empty_indices.append(i)
                non_empty_texts.append(t)

        if not non_empty_texts:
            return [[] for _ in texts]

        try:
            client = self._get_client()
            response = await client.post(
                "/embeddings",
                json={"input": non_empty_texts, "model": self._model},
            )
            response.raise_for_status()
            data = response.json()

            # Sort by index to match input order
            sorted_data = sorted(data["data"], key=lambda d: d["index"])
            api_embeddings = [list(d["embedding"]) for d in sorted_data]

            # Map back to original indices
            result: list[list[float]] = [[] for _ in texts]
            for idx, embedding in zip(non_empty_indices, api_embeddings):
                result[idx] = embedding
            return result
        except Exception as exc:
            logger.error(
                "Failed to embed batch (count=%d): %s",
                len(texts),
                exc,
                exc_info=True,
            )
            return [[] for _ in texts]

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        with self._lock:
            if self._client is not None:
                await self._client.aclose()
                self._client = None
