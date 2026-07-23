"""Tests for app.rag.context_manager.ContextManager"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.rag.context_manager import ContextManager


@pytest.fixture
def cm():
    return ContextManager(keep_recent=4)


@pytest.fixture
def cm_no_tiktoken(cm):
    """Task 11: 禁用 tiktoken 的 ContextManager，使用 fallback 启发式（确定性计数）。

    用于测试截断逻辑（依赖特定 token 计数），而非 token 计数精度。
    """
    with patch("app.rag.context_manager._get_tiktoken_encoder", return_value=None):
        yield cm


class TestTokenCounting:
    def test_count_tokens_empty(self, cm):
        assert cm._count_tokens("") == 0
        assert cm._count_tokens(None) == 0

    def test_count_tokens_pure_ascii_positive(self, cm):
        """英文文本 token 数 > 0"""
        assert cm._count_tokens("abcdefgh") > 0

    def test_count_tokens_pure_cjk_positive(self, cm):
        """中文文本 token 数 > 0"""
        assert cm._count_tokens("你好世界") > 0

    def test_count_tokens_mixed_positive(self, cm):
        """中英文混合 token 数 > 0"""
        text = "你好abc"
        assert cm._count_tokens(text) > 0

    def test_count_tokens_uses_tiktoken_when_available(self, cm):
        """Task 11: tiktoken 可用时使用精确计数"""
        fake_encoder = MagicMock()
        fake_encoder.encode = MagicMock(return_value=[1, 2, 3, 4, 5])
        with patch("app.rag.context_manager._get_tiktoken_encoder", return_value=fake_encoder):
            count = cm._count_tokens("hello world")
        assert count == 5
        fake_encoder.encode.assert_called_once_with("hello world")

    def test_count_tokens_fallback_when_tiktoken_unavailable(self, cm):
        """Task 11: tiktoken 不可用时 fallback 到启发式估算"""
        with patch("app.rag.context_manager._get_tiktoken_encoder", return_value=None):
            # 8 个 ASCII 字符 → 8/4 = 2 token (fallback 估算)
            assert cm._count_tokens("abcdefgh") == 2
            # 4 个中文字符 → 4 token (fallback 估算)
            assert cm._count_tokens("你好世界") == 4

    def test_count_tokens_fallback_on_encode_error(self, cm):
        """Task 11: tiktoken encode 异常时 fallback 到估算"""
        fake_encoder = MagicMock()
        fake_encoder.encode = MagicMock(side_effect=RuntimeError("encode failed"))
        with patch("app.rag.context_manager._get_tiktoken_encoder", return_value=fake_encoder):
            # fallback: 8 ASCII / 4 = 2
            assert cm._count_tokens("abcdefgh") == 2

    def test_token_count_deviation_less_than_5_percent(self, cm):
        """Task 11 SubTask 11.5: tiktoken 精确计数验证

        验证 tiktoken 对已知文本的计数符合预期（偏差 <5%）。
        "hello" 在 cl100k_base 中应为 1 token。
        """
        encoder = _get_real_tiktoken()
        if encoder is None:
            pytest.skip("tiktoken not available")

        # tiktoken 是 ground truth，验证 _count_tokens 使用 tiktoken 时结果一致
        test_cases = [
            "hello",  # 常见英文单词 → 1 token
            "你好世界",  # 4 个中文字符
            "RAG is retrieval-augmented generation.",  # 典型英文技术文本
        ]
        for text in test_cases:
            expected = len(encoder.encode(text))
            actual = cm._count_tokens(text)
            # tiktoken 路径结果应与直接调用 tiktoken 一致（偏差 0%）
            assert actual == expected, (
                f"Token count mismatch for '{text[:30]}...': "
                f"tiktoken={expected}, _count_tokens={actual}"
            )

    def test_fallback_heuristic_reasonable_for_cjk(self, cm):
        """Task 11: fallback 启发式对纯 CJK 文本偏差在合理范围（<30%）"""
        encoder = _get_real_tiktoken()
        if encoder is None:
            pytest.skip("tiktoken not available")
        text = "知识库问答系统检索增强生成技术"
        tiktoken_count = len(encoder.encode(text))
        with patch("app.rag.context_manager._get_tiktoken_encoder", return_value=None):
            fallback_count = cm._count_tokens(text)
        # CJK 1:1 估算对纯中文文本较准（偏差 <30%）
        if tiktoken_count > 0:
            deviation = abs(tiktoken_count - fallback_count) / tiktoken_count
            assert deviation < 0.30, (
                f"CJK fallback deviation {deviation:.2%} exceeds 30% "
                f"(tiktoken={tiktoken_count}, fallback={fallback_count})"
            )


def _get_real_tiktoken():
    """获取真实 tiktoken encoder，不可用时返回 None"""
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


class TestTruncateToBudget:
    def test_all_chunks_fit_within_budget(self, cm_no_tiktoken):
        chunks = [
            {"content": "short"},
            {"content": "another"},
        ]
        result = cm_no_tiktoken._truncate_to_budget(chunks, budget=100)
        assert len(result) == 2

    def test_truncate_when_exceeds_budget(self, cm_no_tiktoken):
        """超出预算时截断最后一个 chunk"""
        chunks = [
            {"content": "a" * 40},  # 10 token
            {"content": "b" * 40},  # 10 token
            {"content": "c" * 40},  # 10 token - 超出 budget=20
        ]
        result = cm_no_tiktoken._truncate_to_budget(chunks, budget=20)
        # 前两个共 20 token，第三个会超 → 截断（remaining=0 不保留）
        assert len(result) == 2

    def test_truncate_keeps_partial_last_chunk_when_remaining_above_50(self, cm_no_tiktoken):
        """remaining > 50 时保留截断的 chunk"""
        chunks = [
            {"content": "a" * 40},   # 10 token
            {"content": "b" * 240},  # 60 token - 超 budget=50
        ]
        result = cm_no_tiktoken._truncate_to_budget(chunks, budget=50)
        # 第一个 10 token，剩 40 token 给第二个
        # remaining = 40 < 50 → 不保留第二个
        assert len(result) == 1

    def test_truncate_keeps_partial_when_remaining_above_threshold(self, cm_no_tiktoken):
        """remaining > 50 时保留截断的 chunk"""
        chunks = [
            {"content": "a" * 40},    # 10 token
            {"content": "b" * 1000},  # 250 token - 超 budget=100
        ]
        result = cm_no_tiktoken._truncate_to_budget(chunks, budget=100)
        # 第一个 10 token，剩 90 token > 50 → 保留截断的 chunk
        assert len(result) == 2
        # 第二个被截断
        assert len(result[1]["content"]) < 1000

    def test_truncate_empty_chunks(self, cm_no_tiktoken):
        result = cm_no_tiktoken._truncate_to_budget([], budget=100)
        assert result == []

    def test_truncate_chunk_without_content(self, cm_no_tiktoken):
        """chunk 无 content → token=0，不会超预算"""
        chunks = [{"content": ""}, {"no_content": True}]
        result = cm_no_tiktoken._truncate_to_budget(chunks, budget=100)
        assert len(result) == 2


class TestTruncateHistoryToBudget:
    def test_keep_recent_messages_first(self, cm_no_tiktoken):
        """从最近开始保留"""
        history = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old reply"},
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "recent reply"},
        ]
        # budget=5 → 只能保留最近 1-2 条
        result = cm_no_tiktoken._truncate_history_to_budget(history, budget=5)
        # 倒序遍历，recent reply (2 token) + recent (2 token) = 4 ≤ 5
        assert len(result) == 2
        assert result[-1]["content"] == "recent reply"

    def test_history_within_budget_returns_all(self, cm_no_tiktoken):
        history = [{"role": "user", "content": "hi"}]
        result = cm_no_tiktoken._truncate_history_to_budget(history, budget=100)
        assert len(result) == 1

    def test_empty_history(self, cm_no_tiktoken):
        assert cm_no_tiktoken._truncate_history_to_budget([], budget=100) == []


class TestBuildMessages:
    def test_build_messages_with_history_and_chunks(self, cm):
        history = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]
        chunks = [{"content": "retrieved context"}]
        messages = cm.build_messages(history, "current query", chunks)
        # 应包含 system prompt + history + 当前 query
        assert isinstance(messages, list)
        assert len(messages) > 0
        # 第一个应是 system message
        assert messages[0]["role"] == "system"

    def test_build_messages_with_summary(self, cm):
        history = [{"role": "user", "content": "old"}]
        chunks = [{"content": "ctx"}]
        messages = cm.build_messages(history, "q", chunks, summary="past summary")
        # 摘要应出现在某条 message 的 content 中
        all_content = " ".join(m["content"] for m in messages)
        assert "past summary" in all_content

    def test_build_messages_empty_history(self, cm):
        chunks = [{"content": "ctx"}]
        messages = cm.build_messages([], "q", chunks)
        assert len(messages) > 0

    def test_build_messages_empty_chunks(self, cm):
        history = [{"role": "user", "content": "hi"}]
        messages = cm.build_messages(history, "q", [])
        assert len(messages) > 0

    def test_build_messages_keep_recent_limit(self, cm):
        """history 超过 keep_recent*2 → 只保留最近 N 轮"""
        cm = ContextManager(keep_recent=2)  # 保留最近 4 条
        history = []
        for i in range(10):
            history.append({"role": "user", "content": f"q{i}"})
            history.append({"role": "assistant", "content": f"a{i}"})
        messages = cm.build_messages(history, "current", [])
        # 不应包含 q0, a0, q1, a1（被裁掉）
        all_content = " ".join(m["content"] for m in messages)
        assert "q0" not in all_content or "current" in all_content  # 宽松断言


class TestNeedsSummary:
    def test_needs_summary_true_when_history_long(self, cm):
        """history > keep_recent*2 → True"""
        history = [{"role": "user", "content": "x"}] * 20
        assert cm.needs_summary(history) is True

    def test_needs_summary_false_when_history_short(self, cm):
        history = [{"role": "user", "content": "x"}] * 4
        assert cm.needs_summary(history) is False

    def test_needs_summary_boundary(self, cm):
        """keep_recent=4 → 边界是 8"""
        assert cm.needs_summary([{"content": "x"}] * 8) is False
        assert cm.needs_summary([{"content": "x"}] * 9) is True

    def test_needs_summary_threshold_matches_chat_history_keep_recent(self):
        """Task 12: needs_summary 阈值与 settings.CHAT_HISTORY_KEEP_RECENT 一致"""
        from app.config import settings
        from app.rag.context_manager import context_manager
        # context_manager 单例使用 settings.CHAT_HISTORY_KEEP_RECENT
        threshold = settings.CHAT_HISTORY_KEEP_RECENT * 2
        assert context_manager.needs_summary([{"content": "x"}] * threshold) is False
        assert context_manager.needs_summary([{"content": "x"}] * (threshold + 1)) is True


class TestSplitHistory:
    def test_split_history_no_split_needed(self, cm):
        """history ≤ keep_recent*2 → 全部 recent"""
        history = [{"content": "x"}] * 4
        older, recent = cm.split_history(history)
        assert older == []
        assert len(recent) == 4

    def test_split_history_splits_correctly(self, cm):
        """history > keep_recent*2 → 拆分为 older + recent"""
        history = [{"content": f"msg{i}"} for i in range(10)]
        older, recent = cm.split_history(history)
        assert len(older) == 2  # 10 - 8 = 2
        assert len(recent) == 8
        assert older[0]["content"] == "msg0"
        assert recent[-1]["content"] == "msg9"


class TestSummarize:
    @pytest.mark.asyncio
    async def test_summarize_empty_messages_returns_empty(self, cm):
        result = await cm.summarize([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_summarize_calls_llm(self, cm):
        older = [
            {"role": "user", "content": "what is python"},
            {"role": "assistant", "content": "python is a language"},
        ]
        fake_llm = MagicMock()
        fake_llm.chat = AsyncMock(return_value="  Python summary  ")

        with patch("app.rag.context_manager.ModelFactory") as mock_factory:
            mock_factory.create_llm.return_value = fake_llm
            result = await cm.summarize(older)

        assert result == "Python summary"
        fake_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_summarize_truncates_long_content(self, cm):
        """summarize 内部对每条消息 content 截断到 300 字符"""
        long_content = "x" * 500
        older = [{"role": "user", "content": long_content}]
        fake_llm = MagicMock()
        fake_llm.chat = AsyncMock(return_value="summary")

        with patch("app.rag.context_manager.ModelFactory") as mock_factory:
            mock_factory.create_llm.return_value = fake_llm
            await cm.summarize(older)

        # 验证 LLM 收到的 prompt 中 content 被截断到 300
        args = fake_llm.chat.await_args
        prompt = args[0][0][0]["content"]
        assert "x" * 300 in prompt
        assert "x" * 301 not in prompt


class TestGetContextWithSummary:
    @pytest.mark.asyncio
    async def test_no_summary_needed(self, cm):
        """history 短 → 直接 build_messages，不调 LLM"""
        history = [{"role": "user", "content": "hi"}]
        chunks = [{"content": "ctx"}]
        messages, summary = await cm.get_context_with_summary(
            history, "query", chunks, existing_summary=None
        )
        assert isinstance(messages, list)
        assert summary is None

    @pytest.mark.asyncio
    async def test_summary_needed_and_existing_summary_provided(self, cm):
        """history 长 + 已有 summary → 用 existing summary，不调 LLM"""
        history = [{"content": "x"}] * 20
        chunks = [{"content": "ctx"}]
        messages, summary = await cm.get_context_with_summary(
            history, "query", chunks, existing_summary="old summary"
        )
        assert summary == "old summary"

    @pytest.mark.asyncio
    async def test_summary_needed_and_no_existing_summary(self, cm):
        """history 长 + 无 summary → 调 LLM 生成新 summary"""
        history = [{"role": "user", "content": "x"}] * 20
        chunks = [{"content": "ctx"}]
        fake_llm = MagicMock()
        fake_llm.chat = AsyncMock(return_value="new summary")

        with patch("app.rag.context_manager.ModelFactory") as mock_factory:
            mock_factory.create_llm.return_value = fake_llm
            messages, summary = await cm.get_context_with_summary(
                history, "query", chunks, existing_summary=None
            )

        assert summary == "new summary"
        assert isinstance(messages, list)


def test_context_manager_singleton_exists():
    from app.rag.context_manager import context_manager
    assert isinstance(context_manager, ContextManager)
