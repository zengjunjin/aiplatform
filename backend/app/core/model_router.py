"""模型路由器 - 根据策略选择 Provider 并处理 Fallback"""

import asyncio
from collections.abc import AsyncIterator

from loguru import logger

from app.config import settings
from app.models.base import BaseLLMProvider
from app.models.factory import ModelRegistry


class ModelRouter:
    """模型路由器 - 根据策略选择 Provider 并处理 Fallback。

    注意: _round_robin_index 和 _request_counts 使用类变量,
    使得即便每次请求 new 一个 ModelRouter 实例, 轮询和负载计数也能跨请求保持状态。
    """

    # 类级共享状态: 轮询索引（round_robin 策略）
    _round_robin_index: int = 0
    # 类级共享状态: provider_name -> 当前请求数（least_busy 策略）
    _request_counts: dict[str, int] = {}
    # Task 7: asyncio.Lock 保护类级共享状态（_round_robin_index / _request_counts）
    # Task 23: 改为懒加载，避免在事件循环外创建 Lock 导致绑定到错误的 loop
    _lock: asyncio.Lock | None = None

    def __init__(self, strategy: str | None = None):
        self.strategy = strategy or settings.LLM_ROUTING_STRATEGY

    def _get_lock(self) -> asyncio.Lock:
        """懒加载获取 asyncio.Lock，确保在正确的事件循环中创建。"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def select(self, preferred_model: str | None = None) -> BaseLLMProvider:
        """选择最佳可用 Provider

        Args:
            preferred_model: 用户指定的模型名称（Provider name），为 None 时按策略自动选择

        Returns:
            选中的 BaseLLMProvider 实例

        Raises:
            ValueError: 无可用 Provider
        """
        # 如果指定了模型，直接按名称查找
        if preferred_model:
            try:
                provider = ModelRegistry.get(preferred_model)
            except ValueError:
                # 指定的模型不存在于注册表中（可能是前端缓存了旧的默认模型名），
                # 回退到自动选择策略，避免对话完全不可用
                logger.warning(
                    f"Preferred model '{preferred_model}' not found in registry, falling back to auto-select"
                )
            else:
                # 修复（v0.4.0）：is_healthy 检查移到 try-except 外，
                # 避免 "模型不健康" 的 ValueError 被 except 捕获后误回退到 auto-select
                if not provider.is_healthy:
                    raise ValueError(f"Provider '{preferred_model}' is unhealthy")
                return provider

        # 获取所有健康的 Provider
        available = ModelRegistry.get_available()
        if not available:
            raise ValueError("No healthy LLM providers available")

        # 根据策略选择（Task 7: 加锁保护类级共享状态）
        # Task 23: 使用懒加载的 _get_lock() 避免事件循环绑定问题
        async with self._get_lock():
            if self.strategy == "least_busy":
                return self._select_least_busy(available)
            elif self.strategy == "cost_optimized":
                return self._select_cost_optimized(available)
            else:
                # round_robin (默认)
                return self._select_round_robin(available)

    def _select_round_robin(self, available: list[BaseLLMProvider]) -> BaseLLMProvider:
        """轮询策略"""
        if not available:
            raise ValueError("No providers available")
        idx = self._round_robin_index % len(available)
        self._round_robin_index += 1
        return available[idx]

    def _cleanup_stale_counts(self) -> None:
        """清理计数为 0 的 provider 条目，防止 dict 无限增长。

        Provider 下线/移除后，其计数条目会残留。此方法移除所有计数 <= 0 的条目。
        _select_least_busy 会在下次选中时重新初始化为 0，故移除安全。
        """
        stale = [k for k, v in self._request_counts.items() if v <= 0]
        for k in stale:
            self._request_counts.pop(k, None)

    def _select_least_busy(self, available: list[BaseLLMProvider]) -> BaseLLMProvider:
        """选择当前请求数最少的 Provider"""
        if not available:
            raise ValueError("No providers available")
        # 清理计数为 0 的残留条目，防止 Provider 下线/移除后 dict 无限增长
        self._cleanup_stale_counts()
        # 初始化未在计数器中的 provider
        for p in available:
            if p.provider_name not in self._request_counts:
                self._request_counts[p.provider_name] = 0
        # 选择请求数最少的
        selected = min(available, key=lambda p: self._request_counts.get(p.provider_name, 0))
        # 递增计数, 调用方应在完成后调用 _release_request 递减
        self._request_counts[selected.provider_name] = (
            self._request_counts.get(selected.provider_name, 0) + 1
        )
        return selected

    def release(self, provider_name: str) -> None:
        """请求完成后递减计数器(用于 least_busy 策略)。

        调用方在 LLM 请求完成后必须调用此方法释放计数，
        否则 least_busy 策略将失效。
        """
        if provider_name in self._request_counts and self._request_counts[provider_name] > 0:
            self._request_counts[provider_name] -= 1
            # 计数归零时清理残留条目，防止 Provider 下线/移除后 dict 无限增长
            if self._request_counts[provider_name] <= 0:
                self._cleanup_stale_counts()

    def _select_cost_optimized(self, available: list[BaseLLMProvider]) -> BaseLLMProvider:
        """优先选择免费 Provider"""
        if not available:
            raise ValueError("No providers available")
        # 优先选择免费的
        free_providers = [p for p in available if getattr(p, "is_free", False)]
        if free_providers:
            return free_providers[0]
        # 没有免费的就用第一个
        return available[0]

    async def chat_with_fallback(
        self,
        messages: list[dict],
        stream: bool = False,
        preferred_model: str | None = None,
        **kwargs,
    ) -> AsyncIterator[str] | str:
        """带 Fallback 的聊天请求

        注意：此方法被 tests/test_model_router.py 用于验证 fallback 策略，
        当前生产入口未直接调用，但保留以维持测试覆盖率，勿删除。

        Args:
            messages: 消息列表
            stream: 是否流式返回
            preferred_model: 用户指定的模型名称（Provider name），为 None 时按策略自动选择

        Returns:
            流式返回 AsyncIterator[str]，非流式返回 str

        Raises:
            ValueError: 所有 Provider 都失败
        """
        # 1. 获取所有健康的 Provider 作为 fallback 链
        all_available = ModelRegistry.get_available()
        if not all_available:
            raise ValueError("No healthy LLM providers available")

        # 2. 构建尝试顺序：首选 Provider 排最前面
        tried: list[str] = []
        ordered = list(all_available)

        if preferred_model:
            try:
                preferred = ModelRegistry.get(preferred_model)
                if preferred.is_healthy:
                    # 把首选移到最前面
                    if preferred in ordered:
                        ordered.remove(preferred)
                    ordered.insert(0, preferred)
            except ValueError:
                logger.warning(
                    f"Preferred model '{preferred_model}' not found, using auto-selection"
                )

        # 3. 依次尝试
        last_error: Exception | None = None
        for provider in ordered:
            tried.append(provider.provider_name)
            try:
                logger.info(
                    f"Trying provider: {provider.provider_name} (model={provider.model_name})"
                )
                result = await provider.chat(messages, stream=stream, **kwargs)
                # 成功：如果之前有失败的 provider，记录 fallback 事件
                if len(tried) > 1:
                    logger.warning(
                        f"Fallback succeeded: tried {tried[:-1]}, "
                        f"final={provider.provider_name}"
                    )
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Provider '{provider.provider_name}' failed: {e}, "
                    f"trying next in fallback chain..."
                )
                continue

        # 4. 所有 Provider 都失败
        raise ValueError(f"All LLM providers failed (tried: {tried}). " f"Last error: {last_error}")
