"""Local bge-reranker-base provider using sentence-transformers.

Sets HF_ENDPOINT to the Chinese mirror (hf-mirror.com) so the model
can be downloaded without accessing huggingface.co directly (which is
often unreachable from mainland China).
"""

import asyncio
import os

from loguru import logger

from app.config import settings
from app.models.base import BaseRerankerProvider

# Use HuggingFace mirror to bypass network issues in mainland China.
# This must be set BEFORE importing sentence_transformers / transformers.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class LocalBgeRerankerProvider(BaseRerankerProvider):
    """Loads bge-reranker-base via sentence-transformers CrossEncoder.

    Uses asyncio.to_thread to avoid blocking the event loop during
    model loading and inference.
    """

    def __init__(self, model_name: str | None = None):
        self._model_name = model_name or settings.RERANKER_MODEL
        self._model = None
        self._load_event: asyncio.Event | None = None
        self._init_lock = asyncio.Lock()

    def _load_model_sync(self):
        """Synchronous model loading (runs in thread pool)."""
        from sentence_transformers import CrossEncoder

        logger.info(f"Loading reranker model: {self._model_name}")
        model = CrossEncoder(self._model_name)
        logger.info(f"Reranker model loaded: {self._model_name}")
        return model

    async def _ensure_model(self):
        """Ensure model is loaded, using thread pool to avoid blocking.

        Only the first caller triggers the load; others wait for it to finish.
        On failure, resets state so the next caller retries.
        """
        if self._model is not None:
            return self._model

        async with self._init_lock:
            if self._model is not None:
                return self._model

            if self._load_event is None:
                # First caller: start loading
                self._load_event = asyncio.Event()
                try:
                    self._model = await asyncio.to_thread(self._load_model_sync)
                except Exception as exc:
                    logger.error(f"Reranker model load failed: {exc}")
                    # Reset state so the next caller retries
                    self._load_event = None
                    raise
                finally:
                    self._load_event.set()
            else:
                # Another coroutine is loading, wait for it
                await self._load_event.wait()

        return self._model

    def _rerank_sync(self, query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
        """Synchronous reranking (runs in thread pool).

        Falls back to returning top_k documents in original order if model
        is unavailable (load failed or not yet loaded).
        """
        model = self._model
        if model is None:
            logger.warning("Reranker model not loaded, skipping rerank")
            return [(i, 0.0) for i in range(min(top_k, len(documents)))]
        pairs = [(query, doc) for doc in documents]
        scores = model.predict(pairs)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

    async def rerank(
        self, query: str, documents: list[str], top_k: int = 5
    ) -> list[tuple[int, float]]:
        if not documents:
            return []
        await self._ensure_model()
        return await asyncio.to_thread(self._rerank_sync, query, documents, top_k)
