"""Tests for app.services.evaluation_service

使用 mock AsyncSession 测试业务逻辑，不依赖真实 PostgreSQL / LLM / RAG。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import NotFoundError
from app.db.document_chunk import DocumentChunk
from app.db.evaluation import EvaluationResult, EvaluationRun, EvaluationStatus
from app.db.knowledge_base import KnowledgeBase
from app.services import evaluation_service

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

        # Mock _generate_question_from_chunk 返回 dict (Task 1.5: question/question_type/difficulty)
        async def fake_gen(content):
            return {
                "question": f"关于 {content[:6]} 的问题？",
                "question_type": "factual",
                "difficulty": "medium",
            }

        fake_ground_truth = "参考答案"
        fake_contexts = [{"content": "ctx1"}, {"content": "ctx2"}]

        with (
            patch.object(
                evaluation_service,
                "_generate_question_from_chunk",
                new=AsyncMock(side_effect=fake_gen),
            ),
            patch.object(
                evaluation_service,
                "_generate_ground_truth",
                new=AsyncMock(return_value=fake_ground_truth),
            ),
            patch.object(
                evaluation_service.retriever, "retrieve", new=AsyncMock(return_value=fake_contexts)
            ),
        ):
            result = await evaluation_service.generate_test_dataset(kb_id=1, db=db, num_questions=5)

        assert len(result) == 2
        assert "question" in result[0]
        assert "ground_truth" in result[0]
        assert "contexts" in result[0]
        # Task 1.5: ground_truth 由 LLM 独立生成，不再来自 chunk.content
        assert result[0]["ground_truth"] == fake_ground_truth
        # contexts 由 retriever 重新检索得到，与 ground_truth 不同源
        assert result[0]["contexts"] == ["ctx1", "ctx2"]

    @pytest.mark.asyncio
    async def test_skips_chunks_when_question_generation_fails(self):
        kb = _make_kb()
        chunks = [
            _make_chunk(chunk_id=10, content="chunk A"),
            _make_chunk(chunk_id=11, content="chunk B"),
            _make_chunk(chunk_id=12, content="chunk C"),
        ]
        db = _mock_db_kb_then_chunks(kb, chunks)

        # 第一个 chunk 返回 None（失败），第二个返回 dict，第三个抛异常
        async def fake_gen(content):
            if "A" in content:
                return None
            if "C" in content:
                raise RuntimeError("LLM error")
            return {
                "question": "chunk B 的问题？",
                "question_type": "factual",
                "difficulty": "medium",
            }

        fake_ground_truth = "参考答案"
        fake_contexts = [{"content": "ctx1"}]

        with (
            patch.object(
                evaluation_service,
                "_generate_question_from_chunk",
                new=AsyncMock(side_effect=fake_gen),
            ),
            patch.object(
                evaluation_service,
                "_generate_ground_truth",
                new=AsyncMock(return_value=fake_ground_truth),
            ),
            patch.object(
                evaluation_service.retriever, "retrieve", new=AsyncMock(return_value=fake_contexts)
            ),
        ):
            result = await evaluation_service.generate_test_dataset(kb_id=1, db=db)

        # 只有 chunk B 成功
        assert len(result) == 1
        assert result[0]["ground_truth"] == fake_ground_truth

    @pytest.mark.asyncio
    async def test_num_questions_limits_sample_size(self):
        kb = _make_kb()
        # 模拟 10 个 chunk，但 num_questions=3
        chunks = [_make_chunk(chunk_id=i, content=f"chunk {i}") for i in range(10)]
        db = _mock_db_kb_then_chunks(kb, chunks)

        async def fake_gen(content):
            return {
                "question": "问题" + content,
                "question_type": "factual",
                "difficulty": "medium",
            }

        fake_ground_truth = "参考答案"
        fake_contexts = [{"content": "ctx1"}]

        with (
            patch.object(
                evaluation_service,
                "_generate_question_from_chunk",
                new=AsyncMock(side_effect=fake_gen),
            ) as mock_gen,
            patch.object(
                evaluation_service,
                "_generate_ground_truth",
                new=AsyncMock(return_value=fake_ground_truth),
            ),
            patch.object(
                evaluation_service.retriever, "retrieve", new=AsyncMock(return_value=fake_contexts)
            ),
        ):
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

        # Task 1.5: 返回 dict，包含 question/question_type/difficulty
        # 非 JSON 输入走 parse_question_response 的 fallback 分支，标签默认 factual/medium
        assert result is not None
        assert result["question"] == "什么是 RAG？"
        assert result["question_type"] == "factual"
        assert result["difficulty"] == "medium"

    @pytest.mark.asyncio
    async def test_question_prefix_stripped(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="问题：什么是 RAG？")

        with patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm):
            result = await evaluation_service._generate_question_from_chunk("content")

        # Task 1.5: 返回 dict；sanitize_question 仍会去除 "问题：" 前缀
        assert result is not None
        assert result["question"] == "什么是 RAG？"
        assert result["question_type"] == "factual"
        assert result["difficulty"] == "medium"

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

        with (
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=chunks)),
            patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm),
            patch("app.rag.prompt_builder.build_rag_prompt", return_value="prompt"),
        ):
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
        """修复（v0.4.0）：get_rag_answer 移除了宽泛 except Exception，
        retriever 异常现在直接向上抛出，由 _run_evaluations 的 gather(return_exceptions=True) 捕获。
        之前吞异常导致失败题目被记为"成功评估"，错误答案污染聚合结果。
        """
        with patch(
            "app.rag.retriever.retriever.retrieve",
            new=AsyncMock(side_effect=RuntimeError("retriever down")),
        ):
            # 异常应直接传播，由调用方 _run_evaluations 做失败隔离
            with pytest.raises(RuntimeError, match="retriever down"):
                await evaluation_service.get_rag_answer("query", kb_id=1)

    @pytest.mark.asyncio
    async def test_empty_answer_replaced_with_empty_string(self):
        chunks = [{"content": "ctx"}]
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value=None)  # LLM 返回 None

        with (
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=chunks)),
            patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm),
            patch("app.rag.prompt_builder.build_rag_prompt", return_value="prompt"),
        ):
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

        with (
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(side_effect=fake_retrieve)),
            patch("app.models.factory.ModelFactory.create_llm", return_value=fake_llm),
            patch("app.rag.prompt_builder.build_rag_prompt", return_value="prompt"),
        ):
            await evaluation_service.get_rag_answer("query", kb_id=1)

        assert captured_top_k == [settings.RETRIEVAL_TOP_K]
        # 确保不是旧的硬编码值 5（除非 settings 恰好配置为 5）
        assert settings.RETRIEVAL_TOP_K == 10  # 默认值


# ---------- _generate_ground_truth ----------


class TestGenerateGroundTruth:
    @pytest.mark.asyncio
    async def test_normal_path_returns_stripped_response(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="  参考答案  ")

        result = await evaluation_service._generate_ground_truth(
            fake_llm, "什么是 RAG？", "KB 描述"
        )

        assert result == "参考答案"
        fake_llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_response_raises_runtime_error(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value="   ")

        with pytest.raises(RuntimeError, match="empty ground_truth"):
            await evaluation_service._generate_ground_truth(
                fake_llm, "什么是 RAG？", "KB 描述"
            )

    @pytest.mark.asyncio
    async def test_none_response_raises_runtime_error(self):
        fake_llm = AsyncMock()
        fake_llm.chat = AsyncMock(return_value=None)

        with pytest.raises(RuntimeError, match="empty ground_truth"):
            await evaluation_service._generate_ground_truth(
                fake_llm, "什么是 RAG？", "KB 描述"
            )


# ---------- trigger_evaluation ----------


def _make_eval_db(run_id: int = 42, refresh_id: int | None = None):
    """构造一个用于 evaluation_service 的 mock AsyncSession。

    - db.add: 同步 mock（用于 EvaluationRun 创建）
    - db.commit / db.refresh: AsyncMock，refresh 将 run.id 设置为指定值
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    expected_id = refresh_id if refresh_id is not None else run_id

    async def fake_refresh(obj, *args, **kwargs):
        obj.id = expected_id

    db.refresh = AsyncMock(side_effect=fake_refresh)
    return db


class TestTriggerEvaluation:
    @pytest.mark.asyncio
    async def test_normal_path_dispatches_celery_task(self):
        db = _make_eval_db(run_id=42)
        fake_task = MagicMock()
        fake_task.id = "task-uuid"

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.rag.prompt_builder.get_prompt_version", return_value="v1.0"),
            patch(
                "app.tasks.evaluation_task.run_evaluation_task.delay",
                return_value=fake_task,
            ) as mock_delay,
        ):
            run, task = await evaluation_service.trigger_evaluation(
                kb_id=1, num_questions=10, user_id=1, db=db, trigger_source="manual"
            )

        assert run.id == 42
        assert run.status == EvaluationStatus.PENDING
        assert run.trigger_source == "manual"
        assert run.prompt_version == "v1.0"
        assert run.total_questions == 10
        assert run.created_by == 1
        assert task.id == "task-uuid"
        db.add.assert_called_once()
        db.commit.assert_awaited()
        db.refresh.assert_awaited()
        mock_delay.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_default_trigger_source_is_manual(self):
        db = _make_eval_db(run_id=42)
        fake_task = MagicMock()
        fake_task.id = "task-uuid"

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.rag.prompt_builder.get_prompt_version", return_value="v1.0"),
            patch("app.tasks.evaluation_task.run_evaluation_task.delay", return_value=fake_task),
        ):
            run, _ = await evaluation_service.trigger_evaluation(
                kb_id=1, num_questions=10, user_id=1, db=db
            )

        assert run.trigger_source == "manual"

    @pytest.mark.asyncio
    async def test_scheduled_trigger_source_propagates(self):
        db = _make_eval_db(run_id=42)
        fake_task = MagicMock()
        fake_task.id = "task-uuid"

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.rag.prompt_builder.get_prompt_version", return_value="v1.0"),
            patch("app.tasks.evaluation_task.run_evaluation_task.delay", return_value=fake_task),
        ):
            run, _ = await evaluation_service.trigger_evaluation(
                kb_id=1, num_questions=10, user_id=1, db=db, trigger_source="scheduled"
            )

        assert run.trigger_source == "scheduled"

    @pytest.mark.asyncio
    async def test_prompt_version_fallback_on_exception(self):
        """get_prompt_version 抛异常时回退到 None，run 仍创建成功。"""
        db = _make_eval_db(run_id=42)
        fake_task = MagicMock()
        fake_task.id = "task-uuid"

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch(
                "app.rag.prompt_builder.get_prompt_version",
                side_effect=RuntimeError("no version"),
            ),
            patch("app.tasks.evaluation_task.run_evaluation_task.delay", return_value=fake_task),
        ):
            run, _ = await evaluation_service.trigger_evaluation(
                kb_id=1, num_questions=10, user_id=1, db=db
            )

        assert run.prompt_version is None

    @pytest.mark.asyncio
    async def test_celery_dispatch_failure_marks_run_failed_and_reraises(self):
        """Celery 派发失败：run 标记为 FAILED，commit 成功后重新抛出原异常。"""
        db = _make_eval_db(run_id=42)

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.rag.prompt_builder.get_prompt_version", return_value="v1.0"),
            patch(
                "app.tasks.evaluation_task.run_evaluation_task.delay",
                side_effect=RuntimeError("celery down"),
            ),
        ):
            with pytest.raises(RuntimeError, match="celery down"):
                await evaluation_service.trigger_evaluation(
                    kb_id=1, num_questions=10, user_id=1, db=db
                )

        # 验证 commit 被调用至少 2 次：1) 创建 run 2) 标记 FAILED
        assert db.commit.await_count >= 2
        db.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_celery_dispatch_failure_with_commit_error_triggers_rollback(self):
        """Celery 派发失败且 commit 也失败时执行 rollback，仍重新抛出原异常。"""
        db = _make_eval_db(run_id=42)
        # 第一次 commit（创建 run）成功；第二次 commit（标记 FAILED）失败
        db.commit = AsyncMock(side_effect=[None, RuntimeError("commit failed")])

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.rag.prompt_builder.get_prompt_version", return_value="v1.0"),
            patch(
                "app.tasks.evaluation_task.run_evaluation_task.delay",
                side_effect=RuntimeError("celery down"),
            ),
        ):
            with pytest.raises(RuntimeError, match="celery down"):
                await evaluation_service.trigger_evaluation(
                    kb_id=1, num_questions=10, user_id=1, db=db
                )

        db.rollback.assert_awaited()


# ---------- list_evaluation_runs ----------


def _make_runs_db(runs: list, total: int):
    """构造用于 list_evaluation_runs 的 mock AsyncSession。

    list_evaluation_runs 调用 db.execute 两次：
    1. count_query -> scalar_one() 返回 total
    2. query -> scalars().all() 返回 runs
    """
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = total
    runs_result = MagicMock()
    runs_result.scalars.return_value.all.return_value = runs
    db.execute = AsyncMock(side_effect=[count_result, runs_result])
    return db


class TestListEvaluationRuns:
    @pytest.mark.asyncio
    async def test_list_without_kb_filter(self):
        runs = [MagicMock(id=1), MagicMock(id=2)]
        db = _make_runs_db(runs, total=2)

        result_runs, total = await evaluation_service.list_evaluation_runs(db)

        assert result_runs == runs
        assert total == 2
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_list_with_kb_filter(self):
        runs = [MagicMock(id=1)]
        db = _make_runs_db(runs, total=1)

        result_runs, total = await evaluation_service.list_evaluation_runs(
            db, kb_id=5, page=1, page_size=20
        )

        assert result_runs == runs
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_with_pagination(self):
        runs = [MagicMock(id=21)]
        db = _make_runs_db(runs, total=100)

        result_runs, total = await evaluation_service.list_evaluation_runs(
            db, page=2, page_size=20
        )

        assert result_runs == runs
        assert total == 100

    @pytest.mark.asyncio
    async def test_list_empty_result(self):
        db = _make_runs_db(runs=[], total=0)

        result_runs, total = await evaluation_service.list_evaluation_runs(db)

        assert result_runs == []
        assert total == 0


# ---------- get_evaluation_run ----------


class TestGetEvaluationRun:
    @pytest.mark.asyncio
    async def test_run_found(self):
        run = MagicMock(id=42)
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = run
        db.execute = AsyncMock(return_value=result)

        got = await evaluation_service.get_evaluation_run(run_id=42, user_id=1, db=db)

        assert got is run

    @pytest.mark.asyncio
    async def test_run_not_found_raises(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(NotFoundError):
            await evaluation_service.get_evaluation_run(run_id=999, user_id=1, db=db)


# ---------- delete_evaluation_run ----------


class TestDeleteEvaluationRun:
    @pytest.mark.asyncio
    async def test_run_not_found_raises(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        with pytest.raises(NotFoundError):
            await evaluation_service.delete_evaluation_run(run_id=999, user_id=1, db=db)

    @pytest.mark.asyncio
    async def test_normal_delete_removes_results_and_run(self):
        run = MagicMock()
        run.id = 42
        run.knowledge_base_id = 7

        db = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run
        db.execute = AsyncMock(return_value=run_result)
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.kb_service.get_kb_for_admin", new=AsyncMock()
        ) as mock_admin:
            await evaluation_service.delete_evaluation_run(run_id=42, user_id=1, db=db)

        # kb admin 权限校验
        mock_admin.assert_awaited_once_with(7, 1, db)
        # 显式删除关联 EvaluationResult + 删除 run
        assert db.execute.await_count == 2  # 查 run + delete EvaluationResult
        db.delete.assert_awaited_once_with(run)
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_kb_admin_permission_failure_propagates(self):
        run = MagicMock()
        run.id = 42
        run.knowledge_base_id = 7

        db = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run
        db.execute = AsyncMock(return_value=run_result)

        with patch(
            "app.services.kb_service.get_kb_for_admin",
            new=AsyncMock(side_effect=PermissionError("forbidden")),
        ):
            with pytest.raises(PermissionError):
                await evaluation_service.delete_evaluation_run(run_id=42, user_id=1, db=db)


# ---------- get_evaluation_results ----------


class TestGetEvaluationResults:
    @pytest.mark.asyncio
    async def test_run_not_found_raises(self):
        db = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=run_result)

        with pytest.raises(NotFoundError):
            await evaluation_service.get_evaluation_results(run_id=999, user_id=1, db=db)

    @pytest.mark.asyncio
    async def test_normal_returns_results_with_total(self):
        run = MagicMock(id=42)
        results_list = [MagicMock(id=1), MagicMock(id=2)]

        db = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = results_list
        db.execute = AsyncMock(side_effect=[run_result, count_result, page_result])

        results, total = await evaluation_service.get_evaluation_results(
            run_id=42, user_id=1, db=db
        )

        assert results == results_list
        assert total == 2

    @pytest.mark.asyncio
    async def test_pagination_uses_offset_and_limit(self):
        run = MagicMock(id=42)
        results_list = [MagicMock(id=21)]

        db = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run
        count_result = MagicMock()
        count_result.scalar_one.return_value = 100
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = results_list
        db.execute = AsyncMock(side_effect=[run_result, count_result, page_result])

        results, total = await evaluation_service.get_evaluation_results(
            run_id=42, user_id=1, db=db, page=2, page_size=20
        )

        assert results == results_list
        assert total == 100

    @pytest.mark.asyncio
    async def test_empty_results(self):
        run = MagicMock(id=42)

        db = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[run_result, count_result, page_result])

        results, total = await evaluation_service.get_evaluation_results(
            run_id=42, user_id=1, db=db
        )

        assert results == []
        assert total == 0
