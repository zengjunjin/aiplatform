import hashlib

from loguru import logger

from app.config import settings
from app.models.factory import ModelFactory
from app.rag.prompt_builder import build_context_messages, build_rag_prompt, get_system_prompt

# tiktoken 精确 token 计数（延迟初始化，import 失败时 fallback 到估算方法）
_tiktoken_encoder = None
_tiktoken_available: bool | None = None


def _get_tiktoken_encoder():
    """延迟初始化 tiktoken encoder（cl100k_base 编码，gpt-3.5/4 通用）。

    失败时返回 None，调用方 fallback 到估算方法。
    """
    global _tiktoken_encoder, _tiktoken_available
    if _tiktoken_available is False:
        return None
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    try:
        import tiktoken

        _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        _tiktoken_available = True
        return _tiktoken_encoder
    except Exception as e:
        logger.debug(f"tiktoken not available, falling back to heuristic token counting: {e}")
        _tiktoken_available = False
        return None


class ContextManager:
    """上下文窗口管理: 滑动窗口 + 摘要压缩

    策略:
    - 始终保留最近 N 轮原文 (默认 4 轮 = 8 条消息)
    - 更早的历史: 调用 LLM 生成摘要替代
    - token 预算: 历史 + 检索 + 当前问题 + 输出（值来自 settings）
    - token 计数: 优先使用 tiktoken 精确计数，fallback 到 CJK/ASCII 估算
    """

    def __init__(self, keep_recent: int = 4):
        # Task 11: 移除未使用的 max_tokens 参数，token 预算统一从 settings 读取
        self.keep_recent = keep_recent

    @property
    def HISTORY_TOKEN_BUDGET(self) -> int:
        return settings.HISTORY_TOKEN_BUDGET

    @property
    def RETRIEVAL_TOKEN_BUDGET(self) -> int:
        return settings.RETRIEVAL_TOKEN_BUDGET

    def _count_tokens(self, text: str) -> int:
        """计算 token 数量。

        优先使用 tiktoken 精确计数（cl100k_base 编码）；
        tiktoken 不可用时 fallback 到启发式估算（CJK 1:1, ASCII 4:1）。
        """
        if not text:
            return 0
        encoder = _get_tiktoken_encoder()
        if encoder is not None:
            try:
                return len(encoder.encode(text))
            except Exception as e:
                logger.debug(f"tiktoken encode failed, fallback to estimation: {e}")
        # Fallback: 中文字符约 1:1, 英文约 4:1
        cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        ascii_count = len(text) - cjk_count
        return int(cjk_count + ascii_count / 4)

    def _truncate_text_to_tokens(self, text: str, token_budget: int) -> str:
        """按 token 预算截断文本, 正确处理 CJK 字符.

        CJK 字符约 1 token/字符, ASCII 约 4 字符/token。
        简单地按 token_budget * 4 截断会截断过多 CJK 内容 (CJK 1字符≈1token, 但按4字符/token截断)。
        """
        if not text or token_budget <= 0:
            return ""
        used_tokens = 0
        result_chars = []
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                used_tokens += 1
            else:
                used_tokens += 0.25
            if used_tokens > token_budget:
                break
            result_chars.append(ch)
        return "".join(result_chars)

    def _deduplicate(self, chunks: list, history: list) -> list:
        """基于 content 的 sha256 hash 去重。

        先把历史消息的 hash 加入已见集合，再过滤 chunks：
        移除与历史消息内容重复的 chunk，并去除 chunks 内部重复。
        保留首次出现的 chunk。
        """
        seen_hashes = set()
        # 先把历史消息的 hash 加入 seen
        for msg in history:
            content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
            h = hashlib.sha256(content.encode()).hexdigest()
            seen_hashes.add(h)
        # 过滤 chunks
        result = []
        for chunk in chunks:
            content = chunk.get("content", "") if isinstance(chunk, dict) else str(chunk)
            h = hashlib.sha256(content.encode()).hexdigest()
            if h not in seen_hashes:
                seen_hashes.add(h)
                result.append(chunk)
        return result

    def _truncate_to_budget(self, chunks: list[dict], budget: int) -> list[dict]:
        """截断检索片段以适应 token 预算."""
        result = []
        used = 0
        for chunk in chunks:
            chunk_tokens = self._count_tokens(chunk.get("content", ""))
            if used + chunk_tokens > budget:
                # 截断最后一个 chunk 以填满预算
                remaining = budget - used
                if remaining > 50:  # 至少保留 50 token
                    truncated = dict(chunk)
                    truncated["content"] = self._truncate_text_to_tokens(
                        chunk.get("content", ""), remaining
                    )
                    result.append(truncated)
                break
            result.append(chunk)
            used += chunk_tokens
        return result

    def _truncate_history_to_budget(self, history: list[dict], budget: int) -> list[dict]:
        """从最近的开始保留, 截断历史以适应 token 预算."""
        result = []
        used = 0
        for msg in reversed(history):
            msg_tokens = self._count_tokens(msg.get("content", ""))
            if used + msg_tokens > budget:
                break
            result.insert(0, msg)
            used += msg_tokens
        return result

    def build_messages(
        self,
        history: list[dict],
        current_query: str,
        retrieved_chunks: list[dict],
        summary: str | None = None,
    ) -> list[dict]:
        keep_count = self.keep_recent * 2
        recent = history[-keep_count:] if len(history) > keep_count else history

        # 去重：移除与历史消息内容重复的 chunk，并去除 chunks 内部重复
        deduplicated_chunks = self._deduplicate(retrieved_chunks, history)

        # 截断检索片段到 token 预算
        truncated_chunks = self._truncate_to_budget(
            deduplicated_chunks, self.RETRIEVAL_TOKEN_BUDGET
        )

        # 截断历史到 token 预算
        truncated_history = self._truncate_history_to_budget(recent, self.HISTORY_TOKEN_BUDGET)

        rag_context = build_rag_prompt(current_query, truncated_chunks)
        return build_context_messages(
            system_prompt=get_system_prompt(),
            rag_context=rag_context,
            history=truncated_history,
            current_query=current_query,
            summary=summary,
        )

    def needs_summary(self, history: list[dict]) -> bool:
        return len(history) > self.keep_recent * 2

    def split_history(self, history: list[dict]) -> tuple[list[dict], list[dict]]:
        keep_count = self.keep_recent * 2
        if len(history) <= keep_count:
            return [], history
        older = history[:-keep_count]
        recent = history[-keep_count:]
        return older, recent

    async def summarize(self, older_messages: list[dict]) -> str:
        if not older_messages:
            return ""
        llm = ModelFactory.create_llm()
        conversation = "\n".join([f"{m['role']}: {m['content'][:300]}" for m in older_messages])
        prompt = f"请用中文简要点总结以下对话的要点,200字以内,保留关键信息和主题:\n\n{conversation}"
        messages = [{"role": "user", "content": prompt}]
        summary = await llm.chat(messages, temperature=0.3)
        return summary.strip()

    async def get_context_with_summary(
        self,
        history: list[dict],
        current_query: str,
        retrieved_chunks: list[dict],
        existing_summary: str | None = None,
    ) -> tuple[list[dict], str | None]:
        if not self.needs_summary(history):
            messages = self.build_messages(
                history, current_query, retrieved_chunks, existing_summary
            )
            return messages, existing_summary

        older, recent = self.split_history(history)

        if existing_summary:
            messages = self.build_messages(
                recent, current_query, retrieved_chunks, existing_summary
            )
            return messages, existing_summary

        new_summary = await self.summarize(older)
        messages = self.build_messages(recent, current_query, retrieved_chunks, new_summary)
        return messages, new_summary


context_manager = ContextManager(keep_recent=settings.CHAT_HISTORY_KEEP_RECENT)
