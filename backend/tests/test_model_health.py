"""Tests for app.core.model_health.ModelHealthChecker"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.model_health import ModelHealthChecker


def _make_provider(name: str, healthy: bool = True, check_result: bool = True) -> MagicMock:
    """创建一个 mock provider，health_check 返回 check_result"""
    p = MagicMock()
    p.provider_name = name
    p._healthy = healthy
    p.health_check = AsyncMock(return_value=check_result)
    return p


class TestConsecutiveFailuresMarkUnhealthy:
    @pytest.mark.asyncio
    async def test_consecutive_failures_mark_unhealthy(self):
        """连续失败 3 次（MAX_FAILURES=3）后标记 _healthy=False"""
        provider = _make_provider("p0", healthy=True, check_result=False)

        checker = ModelHealthChecker(check_interval=999)

        with patch("app.core.model_health.ModelRegistry") as mock_registry:
            mock_registry.list_all.return_value = ["p0"]
            mock_registry.get.return_value = provider

            # 连续检查 3 次，每次 health_check 返回 False
            for i in range(3):
                await checker._check_all()

        # 3 次失败后 _healthy 应为 False
        assert provider._healthy is False
        assert checker.get_failure_count("p0") == 3
        assert checker.is_healthy("p0") is False

    @pytest.mark.asyncio
    async def test_two_failures_not_marked_unhealthy(self):
        """失败 2 次（< MAX_FAILURES）不标记为 unhealthy"""
        provider = _make_provider("p0", healthy=True, check_result=False)

        checker = ModelHealthChecker(check_interval=999)

        with patch("app.core.model_health.ModelRegistry") as mock_registry:
            mock_registry.list_all.return_value = ["p0"]
            mock_registry.get.return_value = provider

            await checker._check_all()
            await checker._check_all()

        # 2 次失败，未达到 MAX_FAILURES=3，_healthy 仍为 True
        assert provider._healthy is True
        assert checker.get_failure_count("p0") == 2
        assert checker.is_healthy("p0") is True


class TestRecoveryResetsCount:
    @pytest.mark.asyncio
    async def test_recovery_resets_count(self):
        """失败 2 次后成功，验证计数重置 + _healthy=True"""
        provider = _make_provider("p0", healthy=True)

        checker = ModelHealthChecker(check_interval=999)

        with patch("app.core.model_health.ModelRegistry") as mock_registry:
            mock_registry.list_all.return_value = ["p0"]
            mock_registry.get.return_value = provider

            # 失败 2 次
            provider.health_check = AsyncMock(return_value=False)
            await checker._check_all()
            await checker._check_all()
            assert checker.get_failure_count("p0") == 2

            # 成功 1 次
            provider.health_check = AsyncMock(return_value=True)
            await checker._check_all()

        # 计数重置为 0，_healthy 为 True
        assert checker.get_failure_count("p0") == 0
        assert provider._healthy is True
        assert checker.is_healthy("p0") is True

    @pytest.mark.asyncio
    async def test_recovery_after_marked_unhealthy(self):
        """标记为 unhealthy 后恢复，_healthy 重新设为 True"""
        provider = _make_provider("p0", healthy=True)

        checker = ModelHealthChecker(check_interval=999)

        with patch("app.core.model_health.ModelRegistry") as mock_registry:
            mock_registry.list_all.return_value = ["p0"]
            mock_registry.get.return_value = provider

            # 失败 3 次 → 标记 unhealthy
            provider.health_check = AsyncMock(return_value=False)
            for _ in range(3):
                await checker._check_all()
            assert provider._healthy is False

            # 恢复
            provider.health_check = AsyncMock(return_value=True)
            await checker._check_all()

        assert provider._healthy is True
        assert checker.get_failure_count("p0") == 0


class TestTimeoutIsolation:
    @pytest.mark.asyncio
    async def test_timeout_isolation(self):
        """一个 provider health_check 超时不阻塞其他 provider 检查"""
        slow_provider = MagicMock()
        slow_provider._healthy = True
        # 模拟超时：health_check 永远不返回（但 wait_for 会超时）
        async def _slow_check():
            await asyncio.sleep(100)
            return True
        slow_provider.health_check = _slow_check

        fast_provider = _make_provider("p1", healthy=True, check_result=True)

        checker = ModelHealthChecker(check_interval=999)
        # 缩短超时以加速测试
        checker.CHECK_TIMEOUT = 0.5

        with patch("app.core.model_health.ModelRegistry") as mock_registry:
            mock_registry.list_all.return_value = ["slow", "fast"]
            mock_registry.get.side_effect = lambda name: {
                "slow": slow_provider,
                "fast": fast_provider,
            }.get(name)

            await checker._check_all()

        # 超时的 provider 标记为失败（计数+1），但不影响 fast provider
        assert checker.get_failure_count("slow") == 1
        # fast provider 正常检查
        assert checker.get_failure_count("fast") == 0
        assert fast_provider._healthy is True


class TestGatherReturnsExceptions:
    @pytest.mark.asyncio
    async def test_gather_returns_exceptions(self):
        """一个 provider 抛异常，其他仍正常检查"""
        crashing_provider = MagicMock()
        crashing_provider._healthy = True
        crashing_provider.health_check = AsyncMock(side_effect=RuntimeError("boom"))

        normal_provider = _make_provider("p1", healthy=True, check_result=True)

        checker = ModelHealthChecker(check_interval=999)

        with patch("app.core.model_health.ModelRegistry") as mock_registry:
            mock_registry.list_all.return_value = ["crash", "normal"]
            mock_registry.get.side_effect = lambda name: {
                "crash": crashing_provider,
                "normal": normal_provider,
            }.get(name)

            # _check_one 内部已捕获异常，返回 (name, False, error_msg)
            # gather(return_exceptions=True) 作为兜底
            await checker._check_all()

        # 抛异常的 provider 计数+1
        assert checker.get_failure_count("crash") == 1
        # 正常 provider 不受影响
        assert checker.get_failure_count("normal") == 0
        assert normal_provider._healthy is True


class TestEmptyProviders:
    @pytest.mark.asyncio
    async def test_no_providers_returns_early(self):
        """无注册 provider 时 _check_all 直接返回"""
        checker = ModelHealthChecker(check_interval=999)

        with patch("app.core.model_health.ModelRegistry") as mock_registry:
            mock_registry.list_all.return_value = []
            # 不应抛异常
            await checker._check_all()

        assert checker._failure_counts == {}
