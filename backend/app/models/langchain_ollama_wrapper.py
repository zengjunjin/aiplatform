"""Langchain-compatible Ollama wrappers for RAGAS evaluation.

RAGAS requires Langchain BaseLanguageModel and Embeddings to compute metrics.
These wrappers call Ollama HTTP API directly, avoiding the need for
langchain-ollama package (which is not installed in the container).

Used only by RAGAS evaluation pipeline (app.services.evaluation_engine._compute_ragas_metrics).
"""

from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ChatOllama(BaseChatModel):
    """Langchain-compatible ChatOllama using Ollama HTTP API (synchronous).

    RAGAS evaluate() calls LLM synchronously in the worker process; this wrapper
    uses httpx.Client (sync) to avoid event-loop conflicts in Celery prefork.

    H4: 复用长生命周期的 httpx.Client，避免每次 _generate 都建立新连接，
    减少 TCP 握手开销，提升 RAGAS 多次 LLM 调用的整体性能。
    """

    model: str = "qwen2.5:1.5b"
    host: str = "http://ollama:11434"
    temperature: float = 0.3
    timeout: float = 600.0

    def __init__(self, model: str = "qwen2.5:1.5b", host: str = "http://ollama:11434", **kwargs):
        super().__init__(model=model, host=host, **kwargs)
        # H4: 长生命周期 client，复用连接池
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=30),
        )

    @property
    def _llm_type(self) -> str:
        return "ollama-chat"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        ollama_messages = []
        for msg in messages:
            if msg.type == "human":
                role = "user"
            elif msg.type == "ai":
                role = "assistant"
            else:
                role = "system"
            ollama_messages.append({"role": role, "content": msg.content})

        resp = self._client.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": ollama_messages,
                "stream": False,
                "options": {"temperature": self.temperature},
            },
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        generations = [ChatGeneration(message=AIMessage(content=content))]
        return ChatResult(generations=generations)


class OllamaEmbeddings(Embeddings):
    """Langchain-compatible Ollama embeddings using Ollama HTTP API (synchronous).

    H4: 复用长生命周期的 httpx.Client，提升多次 embedding 调用性能。
    """

    model: str = "qwen2.5:1.5b"
    host: str = "http://ollama:11434"
    timeout: float = 120.0

    def __init__(self, model: str = "qwen2.5:1.5b", host: str = "http://ollama:11434", **kwargs):
        self.model = model
        self.host = host
        self.timeout = kwargs.get("timeout", 120.0)
        # H4: 长生命周期 client，复用连接池
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            resp = self._client.post(
                f"{self.host}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            resp.raise_for_status()
            data = resp.json()
            results.append(data.get("embedding", []))
        return results

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]
