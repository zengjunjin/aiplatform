"""Tests for app.models.factory / ollama_provider / reranker_provider"""
import pytest
import json
import sys
from unittest.mock import MagicMock, patch, AsyncMock, mock_open
from app.models import factory
from app.models.factory import ModelFactory
from app.models.base import BaseLLMProvider, BaseEmbeddingProvider, BaseRerankerProvider


# ========== ModelFactory ==========

class TestModelFactory:
    def setup_method(self):
        """每个测试前重置单例缓存"""
        ModelFactory._llm = None
        ModelFactory._embedding = None
        ModelFactory._reranker = None

    def test_create_llm_returns_ollama_provider(self):
        with patch("app.models.factory.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "ollama"
            llm = ModelFactory.create_llm()
        from app.models.ollama_provider import OllamaLLMProvider
        assert isinstance(llm, OllamaLLMProvider)

    def test_create_llm_caches_singleton(self):
        with patch("app.models.factory.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "ollama"
            llm1 = ModelFactory.create_llm()
            llm2 = ModelFactory.create_llm()
        assert llm1 is llm2

    def test_create_llm_unknown_provider_raises(self):
        with patch("app.models.factory.settings") as mock_settings:
            mock_settings.LLM_PROVIDER = "openai"
            with pytest.raises(ValueError):
                ModelFactory.create_llm()

    def test_create_embedding_with_cache_disabled(self):
        with patch("app.models.factory.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = "ollama"
            mock_settings.EMBEDDING_CACHE_ENABLED = False
            emb = ModelFactory.create_embedding()
        from app.models.ollama_provider import OllamaEmbeddingProvider
        assert isinstance(emb, OllamaEmbeddingProvider)

    def test_create_embedding_with_cache_enabled(self):
        with patch("app.models.factory.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = "ollama"
            mock_settings.EMBEDDING_CACHE_ENABLED = True
            emb = ModelFactory.create_embedding()
        from app.models.cached_embedding import CachedEmbeddingProvider
        assert isinstance(emb, CachedEmbeddingProvider)

    def test_create_embedding_caches_singleton(self):
        with patch("app.models.factory.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = "ollama"
            mock_settings.EMBEDDING_CACHE_ENABLED = False
            e1 = ModelFactory.create_embedding()
            e2 = ModelFactory.create_embedding()
        assert e1 is e2

    def test_create_embedding_unknown_provider_raises(self):
        with patch("app.models.factory.settings") as mock_settings:
            mock_settings.EMBEDDING_PROVIDER = "openai"
            mock_settings.EMBEDDING_CACHE_ENABLED = False
            with pytest.raises(ValueError):
                ModelFactory.create_embedding()

    def test_create_reranker_returns_local_provider(self):
        reranker = ModelFactory.create_reranker()
        from app.models.reranker_provider import LocalBgeRerankerProvider
        assert isinstance(reranker, LocalBgeRerankerProvider)

    def test_create_reranker_caches_singleton(self):
        r1 = ModelFactory.create_reranker()
        r2 = ModelFactory.create_reranker()
        assert r1 is r2


# ========== OllamaLLMProvider ==========

class TestOllamaLLMProvider:
    def test_init_uses_settings_defaults(self):
        with patch("app.models.ollama_provider.settings") as mock_settings:
            mock_settings.LLM_MODEL = "llama3"
            mock_settings.OLLAMA_HOST = "http://ollama:11434"
            from app.models.ollama_provider import OllamaLLMProvider
            p = OllamaLLMProvider()
        assert p.model == "llama3"
        assert p.host == "http://ollama:11434"

    def test_init_with_explicit_args(self):
        from app.models.ollama_provider import OllamaLLMProvider
        p = OllamaLLMProvider(model="custom-model", host="http://custom:11434")
        assert p.model == "custom-model"
        assert p.host == "http://custom:11434"

    @pytest.mark.asyncio
    async def test_chat_returns_content(self):
        """chat 非流式调用 → 返回 message.content"""
        from app.models.ollama_provider import OllamaLLMProvider
        p = OllamaLLMProvider(model="llama3", host="http://test:11434")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": "Hello world"}}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.models.ollama_provider.httpx.AsyncClient", return_value=mock_client):
            result = await p.chat([{"role": "user", "content": "hi"}])
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_chat_stream_yields_tokens(self):
        """chat_stream → 逐 token yield"""
        from app.models.ollama_provider import OllamaLLMProvider
        p = OllamaLLMProvider(model="llama3", host="http://test:11434")

        # 模拟流式响应行
        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}),
            json.dumps({"message": {"content": " "}, "done": False}),
            json.dumps({"message": {"content": "world"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        async def fake_aiter_lines():
            for line in lines:
                yield line
        mock_resp.aiter_lines = fake_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.models.ollama_provider.httpx.AsyncClient", return_value=mock_client):
            tokens = []
            async for tok in p.chat_stream([{"role": "user", "content": "hi"}]):
                tokens.append(tok)
        assert tokens == ["Hello", " ", "world"]

    @pytest.mark.asyncio
    async def test_chat_stream_skips_empty_lines(self):
        """空行和 JSON decode error 应被跳过"""
        from app.models.ollama_provider import OllamaLLMProvider
        p = OllamaLLMProvider(model="llama3", host="http://test:11434")

        lines = [
            "",  # 空行
            "   ",  # 空白行
            "{invalid json",  # JSON 错误
            json.dumps({"message": {"content": "ok"}, "done": True}),
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        async def fake_aiter_lines():
            for line in lines:
                yield line
        mock_resp.aiter_lines = fake_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("app.models.ollama_provider.httpx.AsyncClient", return_value=mock_client):
            tokens = []
            async for tok in p.chat_stream([{"role": "user", "content": "hi"}]):
                tokens.append(tok)
        assert tokens == ["ok"]


class TestOllamaEmbeddingProvider:
    def test_init_with_defaults(self):
        with patch("app.models.ollama_provider.settings") as mock_settings:
            mock_settings.EMBEDDING_MODEL = "nomic-embed-text"
            mock_settings.OLLAMA_HOST = "http://ollama:11434"
            mock_settings.EMBEDDING_DIM = 1024
            from app.models.ollama_provider import OllamaEmbeddingProvider
            p = OllamaEmbeddingProvider()
        assert p.model == "nomic-embed-text"
        assert p.host == "http://ollama:11434"
        assert p.dim == 1024

    def test_init_with_explicit_args(self):
        from app.models.ollama_provider import OllamaEmbeddingProvider
        p = OllamaEmbeddingProvider(model="custom-emb", host="http://custom:11434")
        assert p.model == "custom-emb"
        assert p.host == "http://custom:11434"

    @pytest.mark.asyncio
    async def test_embed_returns_vectors(self):
        """embed 多个文本 → 返回向量列表"""
        from app.models.ollama_provider import OllamaEmbeddingProvider
        p = OllamaEmbeddingProvider(model="nomic-embed-text", host="http://test:11434")

        # mock _embed_single 直接返回向量
        with patch.object(p, "_embed_single", new=AsyncMock(side_effect=[[0.1, 0.2], [0.3, 0.4]])):
            result = await p.embed(["hello", "world"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]


# ========== _is_retryable_error ==========

class TestIsRetryableError:
    def test_5xx_http_status_error_retryable(self):
        import httpx
        from app.models.ollama_provider import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 500
        exc = httpx.HTTPStatusError("server error", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is True

    def test_429_retryable(self):
        import httpx
        from app.models.ollama_provider import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 429
        exc = httpx.HTTPStatusError("rate limit", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is True

    def test_4xx_not_retryable(self):
        import httpx
        from app.models.ollama_provider import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 404
        exc = httpx.HTTPStatusError("not found", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is False

    def test_network_error_retryable(self):
        import httpx
        from app.models.ollama_provider import _is_retryable_error
        assert _is_retryable_error(httpx.NetworkError("net down")) is True

    def test_timeout_retryable(self):
        import httpx
        from app.models.ollama_provider import _is_retryable_error
        assert _is_retryable_error(httpx.TimeoutException("timeout")) is True

    def test_connect_error_retryable(self):
        import httpx
        from app.models.ollama_provider import _is_retryable_error
        assert _is_retryable_error(httpx.ConnectError("conn refused")) is True

    def test_other_exception_not_retryable(self):
        from app.models.ollama_provider import _is_retryable_error
        assert _is_retryable_error(ValueError("not retryable")) is False


# ========== LocalBgeRerankerProvider ==========

class TestLocalBgeRerankerProvider:
    def test_init_with_default_model(self):
        with patch("app.models.reranker_provider.settings") as mock_settings:
            mock_settings.RERANKER_MODEL = "bge-reranker-base"
            from app.models.reranker_provider import LocalBgeRerankerProvider
            p = LocalBgeRerankerProvider()
        assert p._model_name == "bge-reranker-base"
        assert p._model is None

    def test_init_with_explicit_model(self):
        from app.models.reranker_provider import LocalBgeRerankerProvider
        p = LocalBgeRerankerProvider(model_name="custom-reranker")
        assert p._model_name == "custom-reranker"

    @pytest.mark.asyncio
    async def test_ensure_model_loads_cross_encoder(self):
        """_ensure_model 第一次调用 → 加载 CrossEncoder"""
        fake_cross_encoder = MagicMock()
        mock_ce_class = MagicMock(return_value=fake_cross_encoder)
        fake_module = MagicMock()
        fake_module.CrossEncoder = mock_ce_class
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}), \
             patch("app.models.reranker_provider.asyncio.to_thread", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            from app.models.reranker_provider import LocalBgeRerankerProvider
            p = LocalBgeRerankerProvider(model_name="bge-reranker")
            model = await p._ensure_model()
        assert model is fake_cross_encoder
        mock_ce_class.assert_called_once_with("bge-reranker")

    @pytest.mark.asyncio
    async def test_ensure_model_caches_loaded_model(self):
        """第二次 _ensure_model 不重新加载"""
        fake_cross_encoder = MagicMock()
        mock_ce_class = MagicMock(return_value=fake_cross_encoder)
        fake_module = MagicMock()
        fake_module.CrossEncoder = mock_ce_class
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}), \
             patch("app.models.reranker_provider.asyncio.to_thread", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)):
            from app.models.reranker_provider import LocalBgeRerankerProvider
            p = LocalBgeRerankerProvider(model_name="bge")
            m1 = await p._ensure_model()
            m2 = await p._ensure_model()
        assert m1 is m2
        mock_ce_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_rerank_empty_documents_returns_empty(self):
        from app.models.reranker_provider import LocalBgeRerankerProvider
        p = LocalBgeRerankerProvider(model_name="bge")
        result = await p.rerank("query", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_returns_top_k_ranked(self):
        from app.models.reranker_provider import LocalBgeRerankerProvider
        p = LocalBgeRerankerProvider(model_name="bge")
        fake_model = MagicMock()
        # predict 返回 3 个分数
        fake_model.predict.return_value = [0.1, 0.9, 0.5]
        p._model = fake_model

        result = await p.rerank("query", ["doc1", "doc2", "doc3"], top_k=2)
        # 应返回 top_k=2，按分数降序
        assert len(result) == 2
        # 第一名是 doc2 (0.9)，第二名是 doc3 (0.5)
        assert result[0] == (1, 0.9)
        assert result[1] == (2, 0.5)

    @pytest.mark.asyncio
    async def test_rerank_top_k_larger_than_docs(self):
        """top_k > len(documents) → 返回全部并排序"""
        from app.models.reranker_provider import LocalBgeRerankerProvider
        p = LocalBgeRerankerProvider(model_name="bge")
        fake_model = MagicMock()
        fake_model.predict.return_value = [0.5, 0.8]
        p._model = fake_model

        result = await p.rerank("q", ["a", "b"], top_k=10)
        assert len(result) == 2
        assert result[0] == (1, 0.8)
