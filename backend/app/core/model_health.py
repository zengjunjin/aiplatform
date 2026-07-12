"""Provider 健康检查器 - 定时检查所有注册 Provider 的健康状态"""

import asyncio
from loguru import logger
from app.models.factory import ModelRegistry
from app.config import settings


class ModelHealthChecker:
    """Provider 健康检查器

    定时对所有注册的 Provider 执行健康检查：
    - 连续失败 3 次标记为 unhealthy
    - 恢复后自动标记为 healthy
    """

    MAX_FAILURES = 3

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
        """检查所有注册的 Provider"""
        provider_names = ModelRegistry.list_all()
        if not provider_names:
            return

        for name in provider_names:
            try:
                provider = ModelRegistry.get(name)
                healthy = await provider.health_check()

                if healthy:
                    # 恢复健康：重置失败计数
                    if self._failure_counts.get(name, 0) >= self.MAX_FAILURES:
                        logger.info(f"Provider '{name}' recovered, marking as healthy")
                    self._failure_counts[name] = 0
                else:
                    # 记录失败
                    self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
                    failures = self._failure_counts[name]
                    logger.warning(
                        f"Provider '{name}' health check failed "
                        f"({failures}/{self.MAX_FAILURES})"
                    )
                    if failures >= self.MAX_FAILURES:
                        logger.error(
                            f"Provider '{name}' marked as unhealthy after "
                            f"{failures} consecutive failures"
                        )
            except Exception as e:
                logger.error(f"Error checking health for provider '{name}': {e}")

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