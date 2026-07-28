"""Local bge-reranker-base provider using sentence-transformers.

Sets HF_ENDPOINT to the Chinese mirror (hf-mirror.com) so the model
can be downloaded without accessing huggingface.co directly (which is
often unreachable from mainland China).
"""

import asyncio
import os

import numpy as np
from loguru import logger

from app.config import settings
from app.models.base import BaseRerankerProvider

# Use HuggingFace mirror to bypass network issues in mainland China.
# This must be set BEFORE importing sentence_transformers / transformers.
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# numpy 1.24+ 移除了 np.long / np.object 等 Python2 时代别名，但
# sentence-transformers / transformers / scipy 的旧版本仍引用这些别名，
# 导致 "module 'numpy' has no attribute 'long'/'ulong'/'object'" 错误。
# 在导入 sentence_transformers 之前补回所有已移除的别名。
if not hasattr(np, "long"):
    np.long = np.int64  # type: ignore[attr-defined]
if not hasattr(np, "ulong"):
    np.ulong = np.uint64  # type: ignore[attr-defined]
if not hasattr(np, "object"):
    np.object = object  # type: ignore[attr-defined]
if not hasattr(np, "bool"):
    np.bool = bool  # type: ignore[attr-defined]
if not hasattr(np, "float"):
    np.float = float  # type: ignore[attr-defined]
if not hasattr(np, "int"):
    np.int = int  # type: ignore[attr-defined]
if not hasattr(np, "str"):
    np.str = str  # type: ignore[attr-defined]
if not hasattr(np, "complex"):
    np.complex = complex  # type: ignore[attr-defined]


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
                event = asyncio.Event()
                self._load_event = event
                try:
                    self._model = await asyncio.to_thread(self._load_model_sync)
                except Exception as exc:
                    logger.error(f"Reranker model load failed: {exc}")
                    # Reset state so the next caller retries
                    self._load_event = None
                    raise
                finally:
                    # 仅 set 当前 event（except 分支已清空 self._load_event，
                    # 但 event 局部变量仍指向原对象，wait 的协程可以解除阻塞）
                    event.set()
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

    def is_loaded(self) -> bool:
        """模型是否已加载到内存。"""
        return self._model is not None

    async def ensure_loaded(self) -> None:
        """确保模型已加载（首次调用触发加载）。"""
        await self._ensure_model()
