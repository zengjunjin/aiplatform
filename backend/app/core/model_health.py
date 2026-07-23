"""Provider 健康检查器 - 定时检查所有注册 Provider 的健康状态"""

import asyncio

from loguru import logger

from app.config import settings
from app.models.factory import ModelRegistry


class ModelHealthChecker:
    """Provider 健康检查器

    定时对所有注册的 Provider 执行健康检查：
    - 连续失败 3 次标记为 unhealthy
    - 恢复后自动标记为 healthy
    - 所有 Provider 并行检查，单个失败/超时不影响其他
    """

    # Task 40: 上限/超时迁移到 config.py，原位置引用 settings
    MAX_FAILURES = settings.LLM_HEALTH_CHECK_MAX_FAILURES
    # 单个 Provider 健康检查超时（秒），避免慢 provider 拖垮整体检查
    CHECK_TIMEOUT = settings.LLM_HEALTH_CHECK_TIMEOUT

    def __init__(self, check_interval: int | None = None):
        self.check_interval = check_interval or settings.LLM_HEALTH_CHECK_INTERVAL
        self._failure_counts: dict[str, int] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        """启动定时健康检查"""
        if self._running:
            logger.warning("ModelHealthChecker is already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"ModelHealthChecker started (interval={self.check_interval}s)")

    async def stop(self):
        """停止健康检查"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ModelHealthChecker stopped")

    async def _run_loop(self):
        """后台健康检查循环"""
        while self._running:
            try:
                await self._check_all()
            except Exception as e:
                logger.error(f"ModelHealthChecker loop error: {e}")
            await asyncio.sleep(self.check_interval)

    async def _check_all(self):
        """检查所有注册的 Provider（并行）

        使用 asyncio.gather 并行执行所有 Provider 的健康检查：
        - 单个 Provider 检查失败/超时不影响其他 Provider
        - 每个 Provider 检查受 CHECK_TIMEOUT 超时约束
        """
        provider_names = ModelRegistry.list_all()
        if not provider_names:
            return

        async def _check_one(name: str) -> tuple[str, bool, str | None]:
            """检查单个 Provider，返回 (name, healthy, error_msg)"""
            try:
                provider = ModelRegistry.get(name)
                healthy = await asyncio.wait_for(
                    provider.health_check(), timeout=self.CHECK_TIMEOUT
                )
                return name, bool(healthy), None
            except asyncio.TimeoutError:
                return name, False, f"timeout after {self.CHECK_TIMEOUT}s"
            except Exception as e:
                return name, False, str(e)

        # 并行检查所有 Provider，return_exceptions=True 作为兜底
        results = await asyncio.gather(
            *[_check_one(name) for name in provider_names],
            return_exceptions=True,
        )

        for result in results:
            # _check_one 内部已捕获异常，这里仅作兜底防护
            if isinstance(result, Exception):
                logger.error(f"Unexpected error in health check: {result}")
                continue

            name, healthy, error = result
            provider = ModelRegistry.get(name)
            if healthy:
                # 恢复健康：重置失败计数 + 标记 provider 为 healthy
                if self._failure_counts.get(name, 0) >= self.MAX_FAILURES:
                    logger.info(f"Provider '{name}' recovered, marking as healthy")
                self._failure_counts[name] = 0
                provider._healthy = True
            else:
                # 记录失败：累加计数，达到 MAX_FAILURES 才标记为 unhealthy
                self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
                failures = self._failure_counts[name]
                logger.warning(
                    f"Provider '{name}' health check failed "
                    f"({failures}/{self.MAX_FAILURES})"
                    + (f": {error}" if error else "")
                )
                if failures >= self.MAX_FAILURES:
                    provider._healthy = False
                    logger.error(
                        f"Provider '{name}' marked as unhealthy after "
                        f"{failures} consecutive failures"
                    )

    def is_healthy(self, provider_name: str) -> bool:
        """检查指定 Provider 是否健康

        注意：此方法反映的是健康检查器内部跟踪的状态，
        实际的健康状态由 Provider.is_healthy 属性决定。
        """
        failures = self._failure_counts.get(provider_name, 0)
        return failures < self.MAX_FAILURES

    def get_failure_count(self, provider_name: str) -> int:
        """获取指定 Provider 的连续失败次数"""
        return self._failure_counts.get(provider_name, 0)


# 全局单例
_health_checker: ModelHealthChecker | None = None


def get_health_checker() -> ModelHealthChecker:
    """获取全局 ModelHealthChecker 单例"""
    global _health_checker
    if _health_checker is None:
        _health_checker = ModelHealthChecker()
    return _health_checker
