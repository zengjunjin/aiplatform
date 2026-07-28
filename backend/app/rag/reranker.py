"""Reranker wrapper using bge-reranker-base."""

import asyncio

from loguru import logger

from app.models.factory import ModelFactory


class Reranker:
    """Reranker wrapper that delegates to a RerankerProvider.

    包含加载超时保护：若模型仍在加载中（首次启动或预热未完成），
    rerank() 最多等待 5 秒，超时后直接返回原 chunks（不重排序），
    避免阻塞 chat SSE 流。模型加载完成后后续请求即可正常重排序。
    """

    # 加载等待超时（秒）：超过此时间仍未加载完成则跳过重排序
    LOAD_WAIT_TIMEOUT = 5.0

    def __init__(self):
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            self._provider = ModelFactory.create_reranker()
        return self._provider

    async def rerank(self, query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
        if not chunks:
            return []

        # 检查模型是否已加载，未加载则尝试等待（带超时）
        provider = self.provider
        # 修复（v0.4.0）：使用公共 API 替代私有属性访问，避免破坏封装
        if not provider.is_loaded():
            try:
                # 带超时地等待模型加载，避免长时间阻塞 chat 流
                await asyncio.wait_for(
                    provider.ensure_loaded(), timeout=self.LOAD_WAIT_TIMEOUT
                )
            except TimeoutError:
                logger.warning(
                    f"Reranker model still loading after {self.LOAD_WAIT_TIMEOUT}s, "
                    "skipping rerank (fallback to original order)"
                )
                # 返回原 chunks（截断到 top_k），不重排序
                return chunks[:top_k]
            except Exception as e:
                # 加载失败，抛出由上层 fallback 处理
                raise

        documents = [c.get("content", "") for c in chunks]
        ranked = await provider.rerank(query, documents, top_k=top_k)
        result = []
        for idx, score in ranked:
            if idx < len(chunks):
                chunk = dict(chunks[idx])
                chunk["rerank_score"] = float(score)
                result.append(chunk)
        return result


reranker = Reranker()
