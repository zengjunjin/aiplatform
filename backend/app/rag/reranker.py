"""Reranker wrapper using bge-reranker-base."""
from typing import Optional
from app.models.factory import ModelFactory


class Reranker:
    """Reranker wrapper that delegates to a RerankerProvider."""

    def __init__(self):
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            self._provider = ModelFactory.create_reranker()
        return self._provider

    async def rerank(self, query: str, chunks: list[dict],
                     top_k: int = 5) -> list[dict]:
        if not chunks:
            return []
        documents = [c.get("content", "") for c in chunks]
        ranked = await self.provider.rerank(query, documents, top_k=top_k)
        result = []
        for idx, score in ranked:
            if idx < len(chunks):
                chunk = dict(chunks[idx])
                chunk["rerank_score"] = float(score)
                result.append(chunk)
        return result


reranker = Reranker()
