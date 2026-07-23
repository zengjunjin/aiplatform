"""Unit tests for rag.prompt_builder module."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.rag.prompt_builder import (
    DEFAULT_PROMPT_VERSION,
    DEFAULT_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_context_messages,
    build_rag_prompt,
    get_prompt_version,
    get_system_prompt,
    load_prompt_templates,
)


SAMPLE_CHUNKS = [
    {"chunk_id": 1, "doc_id": 10, "filename": "manual.pdf", "content": "Warranty is 24 months."},
    {"chunk_id": 2, "doc_id": 20, "filename": "terms.docx", "content": "Service requires receipt."},
]


class TestBuildRagPrompt:
    def test_contains_document_markers(self):
        prompt = build_rag_prompt("What is warranty?", SAMPLE_CHUNKS)
        assert "【文档片段】" in prompt

    def test_contains_citation_numbers(self):
        prompt = build_rag_prompt("Question", SAMPLE_CHUNKS)
        assert "[1]" in prompt
        assert "[2]" in prompt

    def test_contains_filenames(self):
        prompt = build_rag_prompt("Q", SAMPLE_CHUNKS)
        assert "manual.pdf" in prompt
        assert "terms.docx" in prompt

    def test_contains_user_question(self):
        question = "What is the answer?"
        prompt = build_rag_prompt(question, SAMPLE_CHUNKS)
        assert "【用户问题】" in prompt
        assert question in prompt

    def test_empty_chunks(self):
        prompt = build_rag_prompt("Question", [])
        assert "【文档片段】" in prompt
        assert "Question" in prompt

    def test_chunk_content_present(self):
        prompt = build_rag_prompt("Q", SAMPLE_CHUNKS)
        assert "Warranty is 24 months." in prompt
        assert "Service requires receipt." in prompt


class TestBuildContextMessages:
    def test_returns_list(self):
        msgs = build_context_messages(SYSTEM_PROMPT, "context", [], "query")
        assert isinstance(msgs, list)
        assert len(msgs) >= 3  # system + context + user

    def test_system_message_first(self):
        msgs = build_context_messages(SYSTEM_PROMPT, "ctx", [], "q")
        assert msgs[0]["role"] == "system"
        assert SYSTEM_PROMPT in msgs[0]["content"]

    def test_user_query_last(self):
        msgs = build_context_messages(SYSTEM_PROMPT, "ctx", [], "my question")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "my question"

    def test_history_included(self):
        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        msgs = build_context_messages(SYSTEM_PROMPT, "ctx", history, "q")
        assert len(msgs) == 5  # system + context + 2 history + user

    def test_summary_included(self):
        msgs = build_context_messages(SYSTEM_PROMPT, "ctx", [], "q", summary="Old convo summary")
        assert msgs[1]["role"] == "system"
        assert "Old convo summary" in msgs[1]["content"]


# ---------- Task 10: Prompt 模板版本化与热加载 ----------

class TestPromptCacheFallback:
    """Task 10: DB 不可用时 fallback 到默认值"""

    def test_default_system_prompt_exists(self):
        assert DEFAULT_SYSTEM_PROMPT
        assert "知识库问答助手" in DEFAULT_SYSTEM_PROMPT

    def test_default_prompt_version(self):
        assert DEFAULT_PROMPT_VERSION == "default-v1"

    def test_get_system_prompt_returns_default_before_load(self):
        """未调用 load 前返回默认值"""
        # 模块加载时 _prompt_cache 未从 DB 加载，应返回默认值
        prompt = get_system_prompt()
        assert "知识库问答助手" in prompt

    def test_get_prompt_version_returns_default_before_load(self):
        version = get_prompt_version()
        assert version == DEFAULT_PROMPT_VERSION

    @pytest.mark.asyncio
    async def test_load_falls_back_on_db_error(self):
        """DB 异常时 fallback 到默认值，不抛出"""
        # async_session 在 load() 内部 lazy import from app.database，
        # 故需 patch 源模块 app.database.async_session
        with patch("app.database.async_session", side_effect=RuntimeError("DB down")):
            # 不应抛异常
            await load_prompt_templates()
        assert "知识库问答助手" in get_system_prompt()
        assert get_prompt_version() == DEFAULT_PROMPT_VERSION

    @pytest.mark.asyncio
    async def test_load_with_no_db_records_uses_default(self):
        """DB 中无 active prompt → 使用默认值"""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        await load_prompt_templates(db=mock_session)

        assert "知识库问答助手" in get_system_prompt()
        assert get_prompt_version() == DEFAULT_PROMPT_VERSION


class TestPromptHotReload:
    """Task 10: 热加载支持"""

    @pytest.mark.asyncio
    async def test_load_from_db_updates_cache(self):
        """从 DB 加载 active prompt 后，缓存更新"""
        from app.rag.prompt_builder import _prompt_cache
        from app.db.prompt_template import PromptTemplate

        fake_template = MagicMock(spec=PromptTemplate)
        fake_template.content = "你是新版助手。"
        fake_template.version = "v2.0"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = fake_template
        mock_session.execute = AsyncMock(return_value=mock_result)

        # 保存原值
        original_content = _prompt_cache.content
        original_version = _prompt_cache.version
        try:
            await load_prompt_templates(db=mock_session)
            assert get_system_prompt() == "你是新版助手。"
            assert get_prompt_version() == "v2.0"
        finally:
            # 恢复默认值，避免污染其他测试
            _prompt_cache.reload_sync(original_content, original_version)

    @pytest.mark.asyncio
    async def test_reload_sync_updates_cache(self):
        """reload_sync 可手动设置缓存内容"""
        from app.rag.prompt_builder import _prompt_cache
        original_content = _prompt_cache.content
        original_version = _prompt_cache.version
        try:
            _prompt_cache.reload_sync("热加载新 prompt", "v3.0")
            assert get_system_prompt() == "热加载新 prompt"
            assert get_prompt_version() == "v3.0"
        finally:
            _prompt_cache.reload_sync(original_content, original_version)


class TestChatMessagePromptVersion:
    """Task 10: chat_service.save_message 记录 prompt_version"""

    @pytest.mark.asyncio
    async def test_save_assistant_message_records_prompt_version(self):
        from app.services import chat_service

        mock_db = AsyncMock()
        # db.refresh 模拟 DB 回写 id，不应覆盖 prompt_version（否则测试断言失效）
        mock_db.refresh = AsyncMock(side_effect=lambda m: setattr(m, "id", 1))

        with patch("app.rag.prompt_builder.get_prompt_version", return_value="test-v1"):
            msg = await chat_service.save_message(
                session_id=1, role="assistant", content="answer", db=mock_db,
            )

        # 验证 prompt_version 被设置到 ChatMessage 上
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.prompt_version == "test-v1"

    @pytest.mark.asyncio
    async def test_save_user_message_does_not_record_prompt_version(self):
        """user 消息不记录 prompt_version（None）"""
        from app.services import chat_service

        mock_db = AsyncMock()

        msg = await chat_service.save_message(
            session_id=1, role="user", content="question", db=mock_db,
        )

        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.prompt_version is None
