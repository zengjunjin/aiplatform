"""模型路由器 - 根据策略选择 Provider 并处理 Fallback"""

from typing import AsyncIterator
from loguru import logger
from app.models.base import BaseLLMProvider
from app.models.factory import ModelRegistry
from app.config import settings


class ModelRouter:
    """模型路由器 - 根据策略选择 Provider 并处理 Fallback。

    注意: _round_robin_index 和 _request_counts 使用类变量,
    使得即便每次请求 new 一个 ModelRouter 实例, 轮询和负载计数也能跨请求保持状态。
    """

    # 类级共享状态: 轮询索引（round_robin 策略）
    _round_robin_index: int = 0
    # 类级共享状态: provider_name -> 当前请求数（least_busy 策略）
    _request_counts: dict[str, int] = {}

    def __init__(self, strategy: str | None = None):
        self.strategy = strategy or settings.LLM_ROUTING_STRATEGY

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
            provider = ModelRegistry.get(preferred_model)
            if not provider.is_healthy:
                raise ValueError(f"Provider '{preferred_model}' is unhealthy")
            return provider

        # 获取所有健康的 Provider
        available = ModelRegistry.get_available()
        if not available:
            raise ValueError("No healthy LLM providers available")

        # 根据策略选择
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

    def _select_least_busy(self, available: list[BaseLLMProvider]) -> BaseLLMProvider:
        """选择当前请求数最少的 Provider"""
        if not available:
            raise ValueError("No providers available")
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

    def _select_cost_optimized(self, available: list[BaseLLMProvider]) -> BaseLLMProvider:
        """优先选择免费 Provider"""
        if not available:
            raise ValueError("No providers available")
        # 优先选择免费的
        free_providers = [p for p in available if getattr(p, 'is_free', False)]
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

        Args:
            messages: 消息列表
            stream: 是否流式返回
            preferred_model: 首选模型名称
            **kwargs: 传递给 Provider.chat() 的额外参数

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
                logger.warning(f"Preferred model '{preferred_model}' not found, using auto-selection")

        # 3. 依次尝试
        last_error: Exception | None = None
        for provider in ordered:
            tried.append(provider.provider_name)
            try:
                logger.info(f"Trying provider: {provider.provider_name} (model={provider.model_name})")
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
        raise ValueError(
            f"All LLM providers failed (tried: {tried}). "
            f"Last error: {last_error}"
        )