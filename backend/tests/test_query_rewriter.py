"""Tests for app.rag.query_rewriter.

覆盖：
- rewrite_query: 代词消解成功、history 为空跳过、无代词跳过、LLM 失败 fallback 返回原 query
- expand_query: 变体生成成功、多变体、去重、LLM 失败 fallback 返回 [query]
- retrieve_with_expansion: 并行检索、去重合并、top_k 截断、单 query 退化、异常隔离
- 边界：空输入、None 输入、超长输入、非 dict history 条目

所有 LLM 调用均通过 mock 模拟，不依赖真实 Ollama。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag import query_rewriter

# ---------- rewrite_query ----------


class TestRewriteQuery:
    @pytest.mark.asyncio
    async def test_rewrite_query_resolves_pronoun_successfully(self):
        """代词消解成功：history 含代词时调用 LLM 返回重写后的 query。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"  # 含代词 "它"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="RAG 有哪些优点？")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "RAG 有哪些优点？"
        mock_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rewrite_query_empty_history_returns_original(self):
        """history 为空时直接返回原 query，不调用 LLM。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock()

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query("什么是 RAG？", [])

        assert result == "什么是 RAG？"
        mock_llm.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rewrite_query_no_pronoun_skips_llm(self):
        """history 与 query 均无代词时跳过 LLM 调用，直接返回原 query。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "RAG 的架构是怎样的？"  # 无代词

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock()

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "RAG 的架构是怎样的？"
        mock_llm.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rewrite_query_llm_failure_fallback_to_original(self):
        """LLM 调用抛异常时 fallback 返回原 query。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("ollama down"))

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "它有哪些优点？"

    @pytest.mark.asyncio
    async def test_rewrite_query_create_llm_failure_fallback_to_original(self):
        """ModelFactory.create_llm 抛异常时 fallback 返回原 query。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"

        with patch(
            "app.models.factory.ModelFactory.create_llm",
            side_effect=RuntimeError("model unavailable"),
        ):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "它有哪些优点？"

    @pytest.mark.asyncio
    async def test_rewrite_query_llm_returns_empty_fallback(self):
        """LLM 返回空字符串时 fallback 返回原 query。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "它有哪些优点？"

    @pytest.mark.asyncio
    async def test_rewrite_query_llm_returns_whitespace_only_fallback(self):
        """LLM 返回纯空白字符串时（strip 后为空）fallback 返回原 query。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="   \n  \t  ")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "它有哪些优点？"

    @pytest.mark.asyncio
    async def test_rewrite_query_llm_returns_none_fallback(self):
        """LLM 返回 None 时 fallback 返回原 query。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=None)

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "它有哪些优点？"

    @pytest.mark.asyncio
    async def test_rewrite_query_history_longer_than_three_uses_recent_only(self):
        """history 长度 > 3 时代词检测只取最近 3 轮，旧 history 中的代词不触发 LLM。"""
        history = [
            {"role": "user", "content": "它是什么？"},  # 旧 history，含 "它"
            {"role": "assistant", "content": "回答"},
            {"role": "user", "content": "什么是 Java？"},
            {"role": "assistant", "content": "Java 是编程语言。"},
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        # 最近 3 轮无代词，query 也无代词 → 跳过 LLM
        query = "RAG 的架构是怎样的？"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock()

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "RAG 的架构是怎样的？"
        mock_llm.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rewrite_query_pronoun_in_recent_history_triggers_llm(self):
        """最近 3 轮含代词时触发 LLM 调用。"""
        history = [
            {"role": "user", "content": "之前提到过 RAG"},  # 含 "之前"
            {"role": "assistant", "content": "是的，RAG 是检索增强生成"},
        ]
        query = "请详细说明"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="请详细说明 RAG 检索增强生成")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "请详细说明 RAG 检索增强生成"
        mock_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rewrite_query_passes_temperature_zero(self):
        """rewrite_query 调用 LLM 时使用 temperature=0.0。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="RAG 有哪些优点？")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            await query_rewriter.rewrite_query(query, history)

        args, kwargs = mock_llm.chat.call_args
        assert kwargs.get("temperature") == 0.0


# ---------- expand_query ----------


class TestExpandQuery:
    @pytest.mark.asyncio
    async def test_expand_query_generates_variants_successfully(self):
        """LLM 返回 3 个变体 → 返回 [query, v1, v2, v3]。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="RAG 是什么\n检索增强生成是什么\n解释 RAG 概念")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        assert result == ["什么是 RAG？", "RAG 是什么", "检索增强生成是什么", "解释 RAG 概念"]
        mock_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_expand_query_generates_multiple_variants_with_dedup(self):
        """变体含重复项时去重（保序），与原 query 重复也去除。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="RAG 是什么\n什么是 RAG？\nRAG 是什么\n解释 RAG")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        # 去重后：[原 query, "RAG 是什么", "解释 RAG"]
        # "什么是 RAG？" 与原 query 重复被去除，第二个 "RAG 是什么" 也去除
        assert result == ["什么是 RAG？", "RAG 是什么", "解释 RAG"]

    @pytest.mark.asyncio
    async def test_expand_query_llm_failure_fallback_returns_single(self):
        """LLM 抛异常时 fallback 返回仅含原 query 的单元素列表。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("ollama down"))

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        assert result == ["什么是 RAG？"]

    @pytest.mark.asyncio
    async def test_expand_query_create_llm_failure_fallback(self):
        """ModelFactory.create_llm 抛异常时 fallback 返回 [query]。"""
        query = "什么是 RAG？"

        with patch(
            "app.models.factory.ModelFactory.create_llm",
            side_effect=RuntimeError("model unavailable"),
        ):
            result = await query_rewriter.expand_query(query)

        assert result == ["什么是 RAG？"]

    @pytest.mark.asyncio
    async def test_expand_query_llm_returns_empty_returns_single(self):
        """LLM 返回空字符串时返回 [query]。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        assert result == ["什么是 RAG？"]

    @pytest.mark.asyncio
    async def test_expand_query_llm_returns_none_returns_single(self):
        """LLM 返回 None 时返回 [query]。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=None)

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        assert result == ["什么是 RAG？"]

    @pytest.mark.asyncio
    async def test_expand_query_limits_to_three_variants(self):
        """LLM 返回超过 3 行时只取前 3 个变体（共 4 个元素含原 query）。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="变体1\n变体2\n变体3\n变体4\n变体5")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        assert len(result) == 4
        assert result[0] == "什么是 RAG？"
        assert result[1:] == ["变体1", "变体2", "变体3"]

    @pytest.mark.asyncio
    async def test_expand_query_filters_empty_lines(self):
        """LLM 返回包含空行和纯空白行时被过滤。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="变体1\n\n  \n变体2\n变体3")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        assert result == ["什么是 RAG？", "变体1", "变体2", "变体3"]

    @pytest.mark.asyncio
    async def test_expand_query_strips_whitespace(self):
        """变体前后空白被 strip。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="  变体1  \n\t变体2\t\n变体3")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        assert result == ["什么是 RAG？", "变体1", "变体2", "变体3"]

    @pytest.mark.asyncio
    async def test_expand_query_all_variants_duplicate_with_original(self):
        """所有变体都与原 query 相同时只返回 [query]。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="什么是 RAG？\n什么是 RAG？\n什么是 RAG？")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(query)

        assert result == ["什么是 RAG？"]

    @pytest.mark.asyncio
    async def test_expand_query_passes_temperature_half(self):
        """expand_query 调用 LLM 时使用 temperature=0.5。"""
        query = "什么是 RAG？"
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="变体1\n变体2\n变体3")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            await query_rewriter.expand_query(query)

        args, kwargs = mock_llm.chat.call_args
        assert kwargs.get("temperature") == 0.5


# ---------- retrieve_with_expansion ----------


class TestRetrieveWithExpansion:
    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_parallel_retrieval(self):
        """多个变体并行检索，结果合并。"""
        variants = ["query", "v1", "v2"]
        chunks_per_variant = {
            "query": [{"chunk_id": 1, "content": "a", "score": 0.9}],
            "v1": [{"chunk_id": 2, "content": "b", "score": 0.8}],
            "v2": [{"chunk_id": 3, "content": "c", "score": 0.7}],
        }

        async def fake_retrieve(query, kb_id, top_k):
            return chunks_per_variant.get(query, [])

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        chunk_ids = {c["chunk_id"] for c in result}
        assert chunk_ids == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_dedup_merge_keeps_highest_score(self):
        """相同 chunk_id 的 chunk 去重，保留最高 score。"""
        variants = ["query", "v1"]
        chunks_per_variant = {
            "query": [{"chunk_id": 1, "content": "a", "score": 0.5}],
            "v1": [{"chunk_id": 1, "content": "a", "score": 0.9}],
        }

        async def fake_retrieve(query, kb_id, top_k):
            return chunks_per_variant.get(query, [])

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        assert len(result) == 1
        assert result[0]["chunk_id"] == 1
        assert result[0]["score"] == 0.9

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_top_k_truncation(self):
        """合并后结果按 score 降序截断到 top_k。"""
        variants = ["query"]
        chunks = [
            {"chunk_id": i, "content": f"c{i}", "score": 0.1 * i}
            for i in range(1, 6)  # 5 个 chunk，分数 0.1 ~ 0.5
        ]

        async def fake_retrieve(query, kb_id, top_k):
            return chunks

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=3)

        assert len(result) == 3
        # 按分数降序（浮点数用 approx 避免精度问题：0.1*3 = 0.30000000000000004）
        assert result[0]["score"] == pytest.approx(0.5)
        assert result[1]["score"] == pytest.approx(0.4)
        assert result[2]["score"] == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_single_query_degradation(self):
        """expand_query 只返回原 query（fallback 场景）时正常单次检索。"""
        variants = ["query"]
        chunks = [{"chunk_id": 1, "content": "a", "score": 0.9}]

        async def fake_retrieve(query, kb_id, top_k):
            return chunks

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        assert result == chunks

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_handles_retrieval_exception(self):
        """单个变体检索抛异常时不影响其他变体结果（return_exceptions=True）。"""
        variants = ["query", "v1", "v2"]

        async def fake_retrieve(query, kb_id, top_k):
            if query == "v1":
                raise RuntimeError("retrieval failed")
            if query == "query":
                return [{"chunk_id": 1, "content": "a", "score": 0.9}]
            return [{"chunk_id": 2, "content": "b", "score": 0.8}]

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        # v1 失败被跳过，query 和 v2 的结果正常合并
        chunk_ids = {c["chunk_id"] for c in result}
        assert chunk_ids == {1, 2}

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_skips_chunks_without_chunk_id(self):
        """无 chunk_id 字段的 chunk 被跳过（cid is None 时 continue）。"""
        variants = ["query"]
        chunks = [
            {"content": "no id", "score": 0.9},  # 无 chunk_id
            {"chunk_id": 5, "content": "with id", "score": 0.8},
        ]

        async def fake_retrieve(query, kb_id, top_k):
            return chunks

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        assert len(result) == 1
        assert result[0]["chunk_id"] == 5

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_prefers_rrf_score_over_score(self):
        """优先使用 rrf_score（融合分数），无 rrf_score 时回退 score。"""
        variants = ["query", "v1"]
        chunks_per_variant = {
            "query": [{"chunk_id": 1, "content": "a", "rrf_score": 0.5, "score": 0.9}],
            "v1": [{"chunk_id": 1, "content": "a", "rrf_score": 0.8, "score": 0.1}],
        }

        async def fake_retrieve(query, kb_id, top_k):
            return chunks_per_variant.get(query, [])

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        # 两个变体都命中 chunk_id=1，去重保留 rrf_score 更高的（0.8）
        assert len(result) == 1
        assert result[0]["rrf_score"] == 0.8

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_empty_results(self):
        """所有变体检索都返回空时返回空列表。"""
        variants = ["query", "v1"]

        async def fake_retrieve(query, kb_id, top_k):
            return []

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_none_score_treated_as_zero(self):
        """score 与 rrf_score 均为 None 时回退到 0。"""
        variants = ["query", "v1"]
        chunks_per_variant = {
            "query": [{"chunk_id": 1, "content": "a", "score": None}],
            "v1": [{"chunk_id": 1, "content": "a", "score": 0.1}],
        }

        async def fake_retrieve(query, kb_id, top_k):
            return chunks_per_variant.get(query, [])

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        # None 回退 0，0.1 > 0 保留 v1 的 chunk
        assert len(result) == 1
        assert result[0]["score"] == 0.1

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_passes_top_k_to_retriever(self):
        """top_k 正确传递给每个 retriever.retrieve 调用。"""
        variants = ["query", "v1"]
        captured_top_k = []

        async def fake_retrieve(query, kb_id, top_k):
            captured_top_k.append(top_k)
            return []

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=7)

        assert captured_top_k == [7, 7]

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_default_top_k_is_ten(self):
        """未指定 top_k 时默认值为 10。"""
        variants = ["query"]
        captured_top_k = []

        async def fake_retrieve(query, kb_id, top_k):
            captured_top_k.append(top_k)
            return []

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            await query_rewriter.retrieve_with_expansion("query", kb_id=1)

        assert captured_top_k == [10]

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_sorted_by_score_descending(self):
        """合并后结果按 score 降序排序。"""
        variants = ["query", "v1"]
        chunks_per_variant = {
            "query": [
                {"chunk_id": 1, "content": "a", "score": 0.3},
                {"chunk_id": 2, "content": "b", "score": 0.9},
            ],
            "v1": [
                {"chunk_id": 3, "content": "c", "score": 0.5},
                {"chunk_id": 4, "content": "d", "score": 0.1},
            ],
        }

        async def fake_retrieve(query, kb_id, top_k):
            return chunks_per_variant.get(query, [])

        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=variants)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
        ):
            result = await query_rewriter.retrieve_with_expansion("query", kb_id=1, top_k=10)

        scores = [c["score"] for c in result]
        assert scores == [0.9, 0.5, 0.3, 0.1]


# ---------- 边界情况 ----------


class TestBoundaryCases:
    @pytest.mark.asyncio
    async def test_rewrite_query_empty_string_no_pronoun_skips_llm(self):
        """query 为空字符串且无代词时跳过 LLM，返回空字符串。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = ""

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock()

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        # history 与 query 均无代词 → 跳过 LLM → 返回原 query（空字符串）
        assert result == ""
        mock_llm.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rewrite_query_empty_string_with_pronoun_calls_llm(self):
        """query 为空字符串但 history 含代词时调用 LLM。"""
        history = [
            {"role": "user", "content": "它的功能是什么？"},
            {"role": "assistant", "content": "RAG 用于检索增强。"},
        ]
        query = ""

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="RAG 的功能是什么")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "RAG 的功能是什么"
        mock_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rewrite_query_none_history_returns_query(self):
        """history 为 None 时直接返回原 query（not None 为 True）。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock()

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query("什么是 RAG？", None)

        assert result == "什么是 RAG？"
        mock_llm.chat.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rewrite_query_history_with_non_dict_entries(self):
        """history 含非 dict 元素时不抛异常（isinstance 过滤）。"""
        history = [
            {"role": "user", "content": "什么是 RAG？"},
            "invalid string",  # 非 dict
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="RAG 有哪些优点？")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "RAG 有哪些优点？"
        mock_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rewrite_query_history_entries_missing_content_key(self):
        """history 条目无 content 键时使用默认空字符串（m.get("content", "")）。"""
        history = [
            {"role": "user"},  # 无 content
            {"role": "assistant", "content": "RAG 是检索增强生成。"},
        ]
        query = "它有哪些优点？"

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="RAG 有哪些优点？")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.rewrite_query(query, history)

        assert result == "RAG 有哪些优点？"
        mock_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_expand_query_empty_string(self):
        """query 为空字符串时不抛异常，原 query 作为首元素。"""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="变体1\n变体2")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query("")

        assert result == ["", "变体1", "变体2"]

    @pytest.mark.asyncio
    async def test_expand_query_long_input(self):
        """超长 query 不抛异常，正常生成变体。"""
        long_query = "什么是 RAG？" * 1000  # 约 7000 字符
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="变体1\n变体2\n变体3")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=mock_llm):
            result = await query_rewriter.expand_query(long_query)

        assert result[0] == long_query
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_retrieve_with_expansion_empty_query(self):
        """query 为空字符串时不抛异常。"""
        with (
            patch("app.rag.query_rewriter.expand_query", new=AsyncMock(return_value=[""])),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=[])),
        ):
            result = await query_rewriter.retrieve_with_expansion("", kb_id=1, top_k=10)

        assert result == []
