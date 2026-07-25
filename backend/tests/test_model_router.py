"""Tests for app.core.model_router.ModelRouter"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.model_router import ModelRouter
from app.models.base import BaseLLMProvider


def _make_provider(name: str, healthy: bool = True, is_free: bool = False) -> MagicMock:
    """创建一个 mock BaseLLMProvider"""
    p = MagicMock(spec=BaseLLMProvider)
    p.provider_name = name
    p.model_name = f"model-{name}"
    p.is_healthy = healthy
    p.is_free = is_free
    p.chat = AsyncMock(return_value="ok")
    p.health_check = AsyncMock(return_value=True)
    return p


@pytest.fixture(autouse=True)
def _reset_router_state():
    """每个测试前重置 ModelRouter 类级共享状态，避免测试间干扰"""
    ModelRouter._round_robin_index = 0
    ModelRouter._request_counts = {}
    yield
    ModelRouter._round_robin_index = 0
    ModelRouter._request_counts = {}


class TestRoundRobinSelection:
    def test_round_robin_selection_cycles_through_providers(self):
        """3 个 provider 轮询选路，验证 round_robin_index 递增并循环"""
        providers = [_make_provider(f"p{i}") for i in range(3)]
        router = ModelRouter(strategy="round_robin")

        selected = [router._select_round_robin(providers) for _ in range(7)]

        # 轮询顺序: p0, p1, p2, p0, p1, p2, p0
        expected = ["p0", "p1", "p2", "p0", "p1", "p2", "p0"]
        assert [p.provider_name for p in selected] == expected
        # 注意: self._round_robin_index += 1 会创建实例变量（遮蔽类变量），
        # 所以在同一个 router 实例上检查实例属性
        assert router._round_robin_index == 7

    def test_round_robin_empty_raises(self):
        router = ModelRouter(strategy="round_robin")
        with pytest.raises(ValueError, match="No providers available"):
            router._select_round_robin([])


class TestLeastBusySelection:
    def test_least_busy_selects_min_request_count(self):
        """选 _request_counts 最小的 provider"""
        providers = [_make_provider(f"p{i}") for i in range(3)]
        ModelRouter._request_counts = {"p0": 5, "p1": 0, "p2": 3}

        router = ModelRouter(strategy="least_busy")
        selected = router._select_least_busy(providers)

        assert selected.provider_name == "p1"
        # 选中后计数递增
        assert ModelRouter._request_counts["p1"] == 1

    def test_least_busy_initializes_unseen_providers(self):
        """未在计数器中的 provider 初始化为 0"""
        providers = [_make_provider("p0"), _make_provider("p1")]
        ModelRouter._request_counts = {}

        router = ModelRouter(strategy="least_busy")
        router._select_least_busy(providers)

        # 两个 provider 初始计数都是 0, min 返回第一个(p0), p0 被选中后计数递增到 1
        assert ModelRouter._request_counts["p0"] == 1
        assert ModelRouter._request_counts["p1"] == 0


class TestCostOptimizedSelection:
    def test_cost_optimized_prefers_free_provider(self):
        """选 cost 最低（is_free=True）的 provider"""
        paid = _make_provider("paid", is_free=False)
        free = _make_provider("free", is_free=True)
        providers = [paid, free]

        router = ModelRouter(strategy="cost_optimized")
        selected = router._select_cost_optimized(providers)

        assert selected.provider_name == "free"

    def test_cost_optimized_falls_back_to_first_when_no_free(self):
        """没有免费 provider 时选第一个"""
        providers = [_make_provider("p0", is_free=False), _make_provider("p1", is_free=False)]

        router = ModelRouter(strategy="cost_optimized")
        selected = router._select_cost_optimized(providers)

        assert selected.provider_name == "p0"


class TestReleaseDecrementsCount:
    def test_release_decrements_count(self):
        """release 后 _request_counts 递减"""
        ModelRouter._request_counts = {"p0": 3}

        router = ModelRouter(strategy="least_busy")
        router.release("p0")
        assert ModelRouter._request_counts["p0"] == 2

        router.release("p0")
        assert ModelRouter._request_counts["p0"] == 1

    def test_release_unknown_provider_no_error(self):
        """release 未知 provider 不报错"""
        ModelRouter._request_counts = {}
        router = ModelRouter(strategy="least_busy")
        # 不应抛异常
        router.release("unknown")

    def test_release_does_not_go_negative(self):
        """计数为 0 时 release 不变为负数"""
        ModelRouter._request_counts = {"p0": 0}
        router = ModelRouter(strategy="least_busy")
        router.release("p0")
        assert ModelRouter._request_counts["p0"] == 0


class TestSelectWithPreferredModel:
    @pytest.mark.asyncio
    async def test_preferred_model_not_found_fallback(self):
        """preferred 不存在时正常选路（chat_with_fallback 中 fallback）"""
        providers = [_make_provider("p0"), _make_provider("p1")]
        providers[0].chat = AsyncMock(return_value="result from p0")

        with patch("app.core.model_router.ModelRegistry") as mock_registry:
            mock_registry.get_available.return_value = providers
            # get(preferred) 抛 ValueError → 触发 fallback 逻辑
            mock_registry.get.side_effect = ValueError("not found")

            router = ModelRouter(strategy="round_robin")
            result = await router.chat_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                preferred_model="nonexistent",
            )

        assert result == "result from p0"
        # 第一个 provider 被调用
        providers[0].chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_select_preferred_model_directly(self):
        """select 指定 preferred_model 时直接返回该 provider"""
        provider = _make_provider("p0", healthy=True)

        with patch("app.core.model_router.ModelRegistry") as mock_registry:
            mock_registry.get.return_value = provider

            router = ModelRouter()
            result = await router.select(preferred_model="p0")

        assert result is provider
        mock_registry.get.assert_called_once_with("p0")

    @pytest.mark.asyncio
    async def test_select_preferred_unhealthy_raises(self):
        """select 指定的 preferred_model 不健康时抛 ValueError"""
        provider = _make_provider("p0", healthy=False)

        with patch("app.core.model_router.ModelRegistry") as mock_registry:
            mock_registry.get.return_value = provider

            router = ModelRouter()
            with pytest.raises(ValueError, match="unhealthy"):
                await router.select(preferred_model="p0")


class TestAllProvidersFailed:
    @pytest.mark.asyncio
    async def test_all_providers_failed_raises(self):
        """全失败抛 ValueError"""
        providers = [_make_provider(f"p{i}") for i in range(3)]
        for p in providers:
            p.chat = AsyncMock(side_effect=RuntimeError("provider down"))

        with patch("app.core.model_router.ModelRegistry") as mock_registry:
            mock_registry.get_available.return_value = providers

            router = ModelRouter()
            with pytest.raises(ValueError, match="All LLM providers failed"):
                await router.chat_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                )

    @pytest.mark.asyncio
    async def test_no_available_providers_raises(self):
        """无可用 provider 时抛 ValueError"""
        with patch("app.core.model_router.ModelRegistry") as mock_registry:
            mock_registry.get_available.return_value = []

            router = ModelRouter()
            with pytest.raises(ValueError, match="No healthy LLM providers"):
                await router.chat_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                )


class TestConcurrentSelectThreadSafe:
    @pytest.mark.asyncio
    async def test_concurrent_select_does_not_error(self):
        """并发 select 不出错，所有调用都返回有效 provider"""
        providers = [_make_provider(f"p{i}") for i in range(3)]

        with patch("app.core.model_router.ModelRegistry") as mock_registry:
            mock_registry.get_available.return_value = providers

            router = ModelRouter(strategy="round_robin")
            tasks = [router.select() for _ in range(20)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # 无异常
        for r in results:
            assert not isinstance(r, Exception), f"Unexpected error: {r}"
            assert r in providers
        # 同一 router 实例上的轮询索引应为 20（实例属性）
        assert router._round_robin_index == 20
