"""Tests for app.services.evaluation_service

使用 mock AsyncSession 测试业务逻辑，不依赖真实 PostgreSQL / LLM / RAG。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import evaluation_service
from app.core.exceptions import NotFoundError
from app.db.knowledge_base import KnowledgeBase
from app.db.document_chunk import DocumentChunk


# ---------- 辅助函数 ----------

def _make_kb(kb_id=1, owner_id=1, name="kb1"):
    kb = MagicMock(spec=KnowledgeBase)
    kb.id = kb_id
    kb.owner_id = owner_id
    kb.name = name
    return kb


def _make_chunk(chunk_id=10, kb_id=1, content="RAG 是检索增强生成的缩写。"):
    chunk = MagicMock(spec=DocumentChunk)
    chunk.id = chunk_id
    chunk.kb_id = kb_id
    chunk.content = content
    chunk.chunk_index = 0
    return chunk


def _mock_db_kb_then_chunks(kb, chunks):
    """第一次 execute 返回 KB（scalar_one_or_none），第二次返回 chunks（scalars().all）。"""
    kb_result = MagicMock()
    kb_result.scalar_one_or_none.return_value = kb

    chunk_result = MagicMock()
    chunk_result.scalars.return_value.all.return_value = chunks

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[kb_result, chunk_result])
    return db


def _mock_db_no_kb():
    db = AsyncMock()
    kb_result = MagicMock()
    kb_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=kb_result)
    return db


# ---------- generate_test_dataset ----------

class TestGenerateTestDataset:
    @pytest.mark.asyncio
    async def test_kb_not_found_raises(self):
        db = _mock_db_no_kb()
        with pytest.raises(NotFoundError):
            await evaluation_service.generate_test_dataset(kb_id=999, db=db)

    @pytest.mark.asyncio
    async def test_no_chunks_returns_empty(self):
        kb = _make_kb()
        db = _mock_db_kb_then_chunks(kb, chunks=[])
        result = await evaluation_service.generate_test_dataset(kb_id=1, db=db)
        assert result == []

    @pytest.mark.asyncio
    async def test_normal_path_returns_dataset(self):
        kb = _make_kb()
        chunks = [
            _make_chunk(chunk_id=10, content="RAG 是检索增强生成。"),
            _make_chunk(chunk_id=11, content="向量数据库用于存储嵌入。"),
        ]
        db = _mock_db_kb_then_chunks(kb, chunks)

        # Mock _generate_question_from_chunk 返回不同问题
        async def fake_gen(content):
            return f"关于 {content[:6]} 的问题？"

        with patch.object(evaluation_service, "_generate_question_from_chunk", new=AsyncMock(side_effect=fake_gen)):
            result = await evaluation_service.generate_test_dataset(kb_id=1, db=db, num_questions=5)

        assert len(result) == 2
        assert "question" in result[0]
        assert "ground_truth" in result[0]
        assert "contexts" in result[0]
        assert result[0]["ground_truth"] == chunks[0].content
        assert result[0]["contexts"] == [chunks[0].content]

    @pytest.mark.asyncio
    async def test_skips_chunks_when_question_generation_fails(self):
        kb = _make_kb()
        chunks = [
            _make_chunk(chunk_id=10, content="chunk A"),
            _make_chunk(chunk_id=11, content="chunk B"),
            _make_chunk(chunk_id=12, content="chunk C"),
        ]
        db = _mock_db_kb_then_chunks(kb, chunks)

        # 第一个 chunk 返回 None（失败），第二个返回问题，第三个抛异常
        async def fake_gen(content):
            if "A" in content:
                return None
            if "C" in content:
                raise RuntimeError("LLM error")
            return "chunk B 的问题？"

        with patch.object(evaluation_service, "_generate_question_from_chunk", new=AsyncMock(side_effect=fake_gen)):
            result = await evaluation_service.generate_test_dataset(kb_id=1, db=db)

        # 只有 chunk B 成功
        assert len(result) == 1
        assert result[0]["ground_truth"] == chunks[1].content

    @pytest.mark.asyncio
    async def test_num_questions_limits_sample_size(self):
        kb = _make_kb()
        # 模拟 10 个 chunk，但 num_questions=3
        chunks = [_make_chunk(chunk_id=i, content=f"chunk {i}") for i in range(10)]
        db = _mock_db_kb_then_chunks(kb, chunks)

        async def fake_gen(content):
            return "问题" + content

        with patch.object(evaluation_service, "_generate_question_from_chunk", new=AsyncMock(side_effect=fake_gen)) as mock_gen:
            result = await evaluation_service.generate_test_dataset(kb_id=1, db=db, num_questions=3)

        # _generate_question_from_chunk 应只被调用 3 次
        assert mock_gen.await_count == 3
        assert len(result) == 3


# ---------- _generate_question_from_chunk ----------

class TestGenerateQuestionFromChunk:
    @pytest.mark.asyncio
    async def test_normal_question_returned(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="什么是 RAG？")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm):
            result = await evaluation_service._generate_question_from_chunk("RAG 是检索增强生成。")

        assert result == "什么是 RAG？"

    @pytest.mark.asyncio
    async def test_question_prefix_stripped(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="问题：什么是 RAG？")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm):
            result = await evaluation_service._generate_question_from_chunk("content")

        assert result == "什么是 RAG？"

    @pytest.mark.asyncio
    async def test_short_question_returns_none(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="ab")  # len < 5

        with patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm):
            result = await evaluation_service._generate_question_from_chunk("content")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(side_effect=RuntimeError("LLM down"))

        with patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm):
            result = await evaluation_service._generate_question_from_chunk("content")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm):
            result = await evaluation_service._generate_question_from_chunk("content")

        assert result is None


# ---------- get_rag_answer ----------

class TestGetRagAnswer:
    @pytest.mark.asyncio
    async def test_normal_path_returns_answer_and_contexts(self):
        chunks = [
            {"content": "RAG 是检索增强生成。"},
            {"content": "向量数据库存储嵌入。"},
        ]
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="RAG 是检索增强生成。")

        with patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=chunks)), \
             patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm), \
             patch("app.rag.prompt_builder.build_rag_prompt", return_value="prompt"):
            answer, contexts = await evaluation_service.get_rag_answer("什么是 RAG？", kb_id=1)

        assert answer == "RAG 是检索增强生成。"
        assert len(contexts) == 2
        assert contexts[0] == "RAG 是检索增强生成。"

    @pytest.mark.asyncio
    async def test_empty_contexts_returns_unable_message(self):
        with patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=[])):
            answer, contexts = await evaluation_service.get_rag_answer("query", kb_id=1)

        assert "无法获取" in answer
        assert contexts == []

    @pytest.mark.asyncio
    async def test_exception_returns_error_message(self):
        with patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=RuntimeError("retriever down"))):
            answer, contexts = await evaluation_service.get_rag_answer("query", kb_id=1)

        assert "评估失败" in answer
        assert contexts == []

    @pytest.mark.asyncio
    async def test_empty_answer_replaced_with_empty_string(self):
        chunks = [{"content": "ctx"}]
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value=None)  # LLM 返回 None

        with patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=chunks)), \
             patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm), \
             patch("app.rag.prompt_builder.build_rag_prompt", return_value="prompt"):
            answer, contexts = await evaluation_service.get_rag_answer("query", kb_id=1)

        assert answer == ""
        assert contexts == ["ctx"]

    @pytest.mark.asyncio
    async def test_retrieve_uses_settings_retrieval_top_k(self):
        """Task 9: 评估管线使用 settings.RETRIEVAL_TOP_K 而非硬编码 5"""
        from app.config import settings

        captured_top_k = []

        async def fake_retrieve(query, kb_id, top_k):
            captured_top_k.append(top_k)
            return [{"content": "ctx"}]

        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="answer")

        with patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)), \
             patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm), \
             patch("app.rag.prompt_builder.build_rag_prompt", return_value="prompt"):
            await evaluation_service.get_rag_answer("query", kb_id=1)

        assert captured_top_k == [settings.RETRIEVAL_TOP_K]
        # 确保不是旧的硬编码值 5（除非 settings 恰好配置为 5）
        assert settings.RETRIEVAL_TOP_K == 10  # 默认值
