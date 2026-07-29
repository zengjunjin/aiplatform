"""Tests for app.tasks.evaluation_task.run_evaluation_task"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings

# conftest.py 先加载 pyarrow (→ numpy)；后续 qdrant_client/rank_bm25 再
# `import numpy` 时，Windows 会抛 "ImportError: cannot load module more than
# once per process"（numpy C 扩展冲突）。在导入 evaluation_task 之前注入
# MagicMock 截断 import 链，避免触碰 numpy。
for _stub in ("qdrant_client", "rank_bm25", "app.rag.bm25", "app.rag.retriever"):
    if _stub not in sys.modules:
        sys.modules[_stub] = MagicMock()

from app.db.evaluation import EvaluationStatus
from app.tasks import evaluation_task
from app.tasks.evaluation_task import (
    _create_evaluation_llm,
    _generate_dataset_async,
    _prepare_dataset,
    _run_evaluations,
    _run_single_evaluation,
    run_evaluation_task,
)


class FakeRun:
    """可追踪 status 变更的 EvaluationRun 替身"""

    def __init__(self, run_id: int = 1, status: EvaluationStatus = EvaluationStatus.PENDING):
        self.id = run_id
        self.knowledge_base_id = 1
        self.total_questions = 3
        self._status = status
        self.status_changes: list[EvaluationStatus] = [status]
        self.started_at = None
        self.completed_at = None
        self.metrics = None
        self.error_message = None

    @property
    def status(self) -> EvaluationStatus:
        return self._status

    @status.setter
    def status(self, value: EvaluationStatus) -> None:
        self._status = value
        self.status_changes.append(value)


def _make_mock_session(run: FakeRun) -> MagicMock:
    """构造 mock 同步 session"""
    session = MagicMock()
    session.get.return_value = run
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.add = MagicMock()
    session.close = MagicMock()

    # 模拟 _claim_run 中 UPDATE...RETURNING 将 status 改为 RUNNING 的副作用。
    # _prepare_dataset 在测试中被 patch，故 session.execute 仅在 _claim_run 调用。
    def _execute_side_effect(*args, **kwargs):
        run.status = EvaluationStatus.RUNNING
        result = MagicMock()
        result.scalar_one_or_none.return_value = run.id
        return result

    session.execute = MagicMock(side_effect=_execute_side_effect)
    return session


def _fake_dataset(n: int = 3) -> list[dict]:
    return [
        {"question": f"q{i}", "ground_truth": f"gt{i}", "contexts": [f"c{i}"], "answer": f"a{i}"}
        for i in range(n)
    ]


def _fake_results(n: int = 3) -> list[dict]:
    return [
        {
            "question": f"q{i}",
            "ground_truth": f"gt{i}",
            "answer": f"a{i}",
            "contexts": [f"c{i}"],
            "faithfulness": 0.9,
            "answer_relevancy": 0.8,
            "context_precision": 0.7,
            "context_recall": 0.6,
        }
        for i in range(n)
    ]


class TestRunStateMachinePendingToRunning:
    def test_run_state_machine_pending_to_running(self):
        """PENDING → RUNNING: 验证第一次 commit 前状态被设为 RUNNING"""
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)

        # _prepare_dataset 返回空 → 触发 FAILED，但在此之前 RUNNING 已设置
        with (
            patch.object(evaluation_task, "get_sync_session", return_value=session),
            patch.object(evaluation_task, "_prepare_dataset", return_value=[]),
        ):
            run_evaluation_task(run_id=1)

        # 状态变更: PENDING → RUNNING → FAILED
        assert EvaluationStatus.RUNNING in run.status_changes
        assert run.status_changes[1] == EvaluationStatus.RUNNING
        # 第一次 commit 在 RUNNING 之后
        assert session.commit.call_count >= 1
        # 最终 FAILED（因为 dataset 为空）
        assert run.status == EvaluationStatus.FAILED
        # session 被关闭
        session.close.assert_called_once()


class TestRunSuccessRunningToCompleted:
    def test_run_success_running_to_completed(self):
        """RUNNING → COMPLETED: 完整成功路径"""
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)
        dataset = _fake_dataset(3)
        results = _fake_results(3)
        fake_metrics = {"faithfulness": 0.9, "answer_relevancy": 0.8}

        with (
            patch.object(evaluation_task, "get_sync_session", return_value=session),
            patch.object(evaluation_task, "_prepare_dataset", return_value=dataset),
            patch.object(evaluation_task, "_run_evaluations", return_value=results),
            patch.object(evaluation_task, "aggregate_metrics", return_value=fake_metrics),
        ):
            result = run_evaluation_task(run_id=1)

        # 状态变更: PENDING → RUNNING → COMPLETED
        assert run.status_changes == [
            EvaluationStatus.PENDING,
            EvaluationStatus.RUNNING,
            EvaluationStatus.COMPLETED,
        ]
        # metrics 被设置
        assert run.metrics == fake_metrics
        # 每个结果都被 add_all（批量插入）
        assert session.add_all.call_count == 1
        assert len(session.add_all.call_args[0][0]) == 3
        # 返回值包含 completed 状态和 metrics
        assert result["status"] == "completed"
        assert result["metrics"] == fake_metrics
        assert result["run_id"] == 1
        # session 被关闭
        session.close.assert_called_once()

    def test_run_not_found_returns_error(self):
        """run 不存在时返回 error"""
        session = MagicMock()
        session.get.return_value = None
        session.close = MagicMock()

        with patch.object(evaluation_task, "get_sync_session", return_value=session):
            result = run_evaluation_task(run_id=999)

        assert result == {"error": "already in progress or completed"}
        session.close.assert_called_once()


class TestRunFailureRunningToFailed:
    def test_run_failure_running_to_failed(self):
        """RUNNING → FAILED: 重试次数用尽后标记 FAILED

        修复（v0.4.0）：run_evaluation_task 失败时先 retry，
        重试次数用尽后才 _mark_run_failed。测试模拟 retries 已用尽。
        """
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)
        dataset = _fake_dataset(3)

        eval_task = evaluation_task.run_evaluation_task
        eval_task.push_request(retries=settings.TASK_MAX_RETRIES_EVALUATION)
        try:
            with (
                patch.object(evaluation_task, "get_sync_session", return_value=session),
                patch.object(evaluation_task, "_prepare_dataset", return_value=dataset),
                patch.object(
                    evaluation_task,
                    "_run_evaluations",
                    side_effect=RuntimeError("RAGAS evaluation failed"),
                ),
            ):
                # 重试次数用尽 → 标记 FAILED 后 raise 原始异常
                with pytest.raises(RuntimeError, match="RAGAS evaluation failed"):
                    run_evaluation_task(run_id=1)
        finally:
            eval_task.pop_request()

        # 状态变更: PENDING → RUNNING → FAILED（由 _mark_run_failed 设置）
        assert run.status_changes == [
            EvaluationStatus.PENDING,
            EvaluationStatus.RUNNING,
            EvaluationStatus.FAILED,
        ]
        # error_message 被设置
        assert "评估失败" in run.error_message
        # rollback 被调用（_run_evaluation_async 的 except 块）
        session.rollback.assert_called()
        # session 被关闭（_run_evaluation_async + _mark_run_failed 各一次）
        session.close.assert_called()


class TestCommitErrDoesNotBlock:
    def test_commit_err_does_not_block(self):
        """DB commit 失败不阻断状态更新（_mark_run_failed 内 commit 失败被捕获）

        修复（v0.4.0）：commit 错误在 _mark_run_failed 的 except 中被捕获，
        不影响 status 已被设置在 run 对象上。
        """
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)
        dataset = _fake_dataset(3)

        # commit 调用顺序 (_prepare_dataset 被 patch, 其 commit 不执行):
        # 1. _claim_run 中 RUNNING 后 → None (成功)
        # 2. _update_run_status 中 FAILED 后 → RuntimeError (失败，被 _mark_run_failed except 捕获)
        session.commit.side_effect = [None, RuntimeError("commit failed in except")]

        eval_task = evaluation_task.run_evaluation_task
        eval_task.push_request(retries=settings.TASK_MAX_RETRIES_EVALUATION)
        try:
            with (
                patch.object(evaluation_task, "get_sync_session", return_value=session),
                patch.object(evaluation_task, "_prepare_dataset", return_value=dataset),
                patch.object(
                    evaluation_task, "_run_evaluations", side_effect=RuntimeError("eval error")
                ),
            ):
                # 重试用尽 → _mark_run_failed 中 commit 失败被捕获 → raise 原始异常
                with pytest.raises(RuntimeError, match="eval error"):
                    run_evaluation_task(run_id=1)
        finally:
            eval_task.pop_request()

        # 状态仍被设为 FAILED（在 commit 失败之前已设置到 run 对象上）
        assert run.status == EvaluationStatus.FAILED
        assert "评估失败" in run.error_message
        # rollback 被调用（_run_evaluation_async 的 except 块）
        assert session.rollback.call_count >= 1
        # session 被关闭（多次调用：_run_evaluation_async + _mark_run_failed）
        session.close.assert_called()


class TestDatasetGenerationFailureHandling:
    def test_dataset_generation_failure_handling(self):
        """dataset 生成失败（返回空）标记 run 为 FAILED"""
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)

        with (
            patch.object(evaluation_task, "get_sync_session", return_value=session),
            patch.object(evaluation_task, "_prepare_dataset", return_value=[]),
        ):
            result = run_evaluation_task(run_id=1)

        # 状态变更: PENDING → RUNNING → FAILED
        assert run.status_changes == [
            EvaluationStatus.PENDING,
            EvaluationStatus.RUNNING,
            EvaluationStatus.FAILED,
        ]
        # error_message 包含 "No chunks"
        assert "No chunks" in run.error_message
        # 返回 error
        assert result == {"error": "No chunks available"}
        # completed_at 被设置
        assert run.completed_at is not None
        # session 被关闭
        session.close.assert_called_once()

    def test_dataset_generation_exception_marks_failed(self):
        """_prepare_dataset 抛异常时也标记 FAILED（重试次数用尽后）

        修复（v0.4.0）：异常先 retry，重试用尽后由 _mark_run_failed 标记 FAILED。
        """
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)

        eval_task = evaluation_task.run_evaluation_task
        eval_task.push_request(retries=settings.TASK_MAX_RETRIES_EVALUATION)
        try:
            with (
                patch.object(evaluation_task, "get_sync_session", return_value=session),
                patch.object(
                    evaluation_task, "_prepare_dataset", side_effect=RuntimeError("DB connection lost")
                ),
            ):
                with pytest.raises(RuntimeError, match="DB connection lost"):
                    run_evaluation_task(run_id=1)
        finally:
            eval_task.pop_request()

        # 异常被 except 捕获，状态设为 FAILED（由 _mark_run_failed 设置）
        assert run.status == EvaluationStatus.FAILED
        assert "评估失败" in run.error_message
        session.close.assert_called()


class TestClaimRunIdempotency:
    """_claim_run 幂等性: 已被抢占时 claimed is None 分支 (lines 127-128)"""

    def test_claim_run_already_claimed_returns_none(self):
        """run 已被其他 worker 抢占 (UPDATE...RETURNING 命中 0 行) → 返回 None

        覆盖 _claim_run 中 scalar_one_or_none() is None 的早返回路径。
        """
        session = MagicMock()
        result = MagicMock()
        # UPDATE...RETURNING 未命中任何行 → claimed is None
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result
        session.close = MagicMock()

        with patch.object(evaluation_task, "get_sync_session", return_value=session):
            result_out = run_evaluation_task(run_id=1)

        assert result_out == {"error": "already in progress or completed"}
        # 即使抢占失败也关闭 session
        session.close.assert_called_once()


class TestUpdateRunStatus:
    """_update_run_status: run 不存在分支 (line 144 if run: False)"""

    async def test_update_run_status_run_not_found(self):
        """run 不存在 → 不报错，仍 commit（幂等收尾）"""
        session = MagicMock()
        session.get.return_value = None

        # 不应抛异常；commit 仍被调用以关闭事务
        await evaluation_task._update_run_status(
            session, 999, EvaluationStatus.FAILED, "some error"
        )

        session.commit.assert_called_once()


class TestPrepareDataset:
    """_prepare_dataset: sync 查询 chunks + 调用生成 (lines 158-184)"""

    async def test_prepare_dataset_with_chunks_returns_dataset(self):
        """有 chunks → 更新 total_questions 并调用 _generate_dataset_async"""
        run = FakeRun(status=EvaluationStatus.RUNNING)
        run.knowledge_base_id = 5
        run.total_questions = 3
        session = MagicMock()
        chunks = [MagicMock(content=f"chunk-{i}") for i in range(3)]
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = chunks
        session.execute.return_value = result_mock

        fake_dataset = _fake_dataset(3)
        with patch.object(
            evaluation_task, "_generate_dataset_async", new=AsyncMock(return_value=fake_dataset)
        ):
            result = await _prepare_dataset(session, run)

        assert result == fake_dataset
        # total_questions 被更新为实际 chunk 数
        assert run.total_questions == 3
        # _sync_update_count 中调用了 commit
        session.commit.assert_called()

    async def test_prepare_dataset_no_chunks_returns_empty(self):
        """无 chunks → 直接返回空列表，不调用 _generate_dataset_async"""
        run = FakeRun(status=EvaluationStatus.RUNNING)
        run.total_questions = 3
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute.return_value = result_mock

        with patch.object(
            evaluation_task, "_generate_dataset_async", new=AsyncMock()
        ) as mock_gen:
            result = await _prepare_dataset(session, run)

        assert result == []
        mock_gen.assert_not_awaited()


class TestGenerateDatasetAsync:
    """_generate_dataset_async: 并发 LLM 生成 + 过滤 None (lines 187-221)

    P1-6 修复后：函数内调用 evaluation_service.generate_question_from_chunk /
    generate_ground_truth（不再有 _generate_question_async / _generate_ground_truth_async），
    provider 通过 _create_evaluation_llm 创建（不再硬编码 OllamaLLMProvider）。
    """

    async def test_generate_dataset_async_success(self):
        """所有 chunk 成功生成 → 返回完整数据集，llm.close 被调用"""
        chunks = [MagicMock(content=f"c{i}") for i in range(3)]
        question_data = {"question": "q", "question_type": "factual", "difficulty": "easy"}

        # Mock retriever (app.rag.retriever is stubbed as MagicMock in sys.modules)
        mock_retriever = MagicMock()
        mock_retriever.retrieve = AsyncMock(return_value=[{"content": "ctx1"}])

        mock_llm = AsyncMock()

        with (
            patch.object(sys.modules["app.rag.retriever"], "retriever", mock_retriever),
            patch.object(
                evaluation_task, "_create_evaluation_llm", return_value=mock_llm
            ),
            patch(
                "app.services.evaluation_service.generate_question_from_chunk",
                new=AsyncMock(return_value=question_data),
            ),
            patch(
                "app.services.evaluation_service.generate_ground_truth",
                new=AsyncMock(return_value="ground_truth"),
            ),
        ):
            result = await _generate_dataset_async(chunks, "kb desc", 1)

        assert len(result) == 3
        for item in result:
            assert item["question"] == "q"
            assert item["question_type"] == "factual"
            assert item["difficulty"] == "easy"
            # ground_truth 由 generate_ground_truth 独立生成
            assert item["ground_truth"] == "ground_truth"
            # contexts 由 retriever.retrieve 重新检索得到
            assert item["contexts"] == ["ctx1"]
        # finally 块: llm.close 总被调用
        mock_llm.close.assert_awaited_once()

    async def test_generate_dataset_async_filters_none(self):
        """部分 chunk 生成失败 (返回 None) → 被过滤掉"""
        chunks = [MagicMock(content="c0"), MagicMock(content="c1")]
        question_data = {"question": "q", "question_type": "factual", "difficulty": "easy"}

        mock_retriever = MagicMock()
        mock_retriever.retrieve = AsyncMock(return_value=[{"content": "ctx1"}])

        mock_llm = AsyncMock()

        with (
            patch.object(sys.modules["app.rag.retriever"], "retriever", mock_retriever),
            patch.object(
                evaluation_task, "_create_evaluation_llm", return_value=mock_llm
            ),
            patch(
                "app.services.evaluation_service.generate_question_from_chunk",
                new=AsyncMock(side_effect=[None, question_data]),
            ),
            patch(
                "app.services.evaluation_service.generate_ground_truth",
                new=AsyncMock(return_value="ground_truth"),
            ),
        ):
            result = await _generate_dataset_async(chunks, "kb desc", 1)

        # None 被过滤，只保留 1 条
        assert len(result) == 1
        assert result[0]["question"] == "q"
        mock_llm.close.assert_awaited_once()

    async def test_generate_dataset_async_empty_chunks(self):
        """空 chunks 列表 → 返回空数据集，llm.close 仍被调用"""
        mock_llm = AsyncMock()

        with (
            patch.object(
                evaluation_task, "_create_evaluation_llm", return_value=mock_llm
            ),
            patch(
                "app.services.evaluation_service.generate_question_from_chunk",
                new=AsyncMock(),
            ),
        ):
            result = await _generate_dataset_async([], "kb desc", 1)

        assert result == []
        mock_llm.close.assert_awaited_once()


class TestRunEvaluations:
    """_run_evaluations: 并发评估 + 异常转错误条目 (lines 249-281)

    P1-6 修复后：provider 通过 _create_evaluation_llm 创建（不再硬编码 OllamaLLMProvider）。
    """

    async def test_run_evaluations_all_success(self):
        """所有问题评估成功 → 返回所有结果"""
        dataset = _fake_dataset(3)
        single_result = {
            "question": "q", "ground_truth": "gt", "answer": "a",
            "contexts": ["c"], "faithfulness": 0.9,
        }
        mock_llm = AsyncMock()

        with (
            patch.object(
                evaluation_task, "_create_evaluation_llm", return_value=mock_llm
            ),
            patch.object(
                evaluation_task, "_run_single_evaluation", new=AsyncMock(return_value=single_result)
            ),
        ):
            results = await _run_evaluations(kb_id=1, dataset=dataset)

        assert len(results) == 3
        assert all(r["faithfulness"] == 0.9 for r in results)
        # finally 块: llm.close 被调用
        mock_llm.close.assert_awaited_once()

    async def test_run_evaluations_exception_converted_to_error_entry(self):
        """单题评估抛异常 → 转为错误条目，不阻断整体"""
        dataset = [
            {"question": "q0", "ground_truth": "gt0", "contexts": ["c0"]},
            {"question": "q1", "ground_truth": "gt1", "contexts": ["c1"]},
        ]
        ok_result = {
            "question": "q1", "ground_truth": "gt1", "answer": "a1",
            "contexts": ["c1"], "faithfulness": 0.8,
        }
        mock_llm = AsyncMock()

        with (
            patch.object(
                evaluation_task, "_create_evaluation_llm", return_value=mock_llm
            ),
            patch.object(
                evaluation_task,
                "_run_single_evaluation",
                new=AsyncMock(side_effect=[RuntimeError("eval failed"), ok_result]),
            ),
        ):
            results = await _run_evaluations(kb_id=1, dataset=dataset)

        assert len(results) == 2
        # 第一题异常 → 错误条目（保留 question/ground_truth/contexts）
        assert results[0]["answer"] == "评估失败，请稍后重试"
        assert results[0]["question"] == "q0"
        assert results[0]["ground_truth"] == "gt0"
        assert results[0]["contexts"] == ["c0"]
        # 第二题正常
        assert results[1]["answer"] == "a1"
        assert results[1]["faithfulness"] == 0.8
        mock_llm.close.assert_awaited_once()

    async def test_run_evaluations_empty_dataset(self):
        """空数据集 → 返回空列表"""
        mock_llm = AsyncMock()

        with (
            patch.object(
                evaluation_task, "_create_evaluation_llm", return_value=mock_llm
            ),
            patch.object(
                evaluation_task, "_run_single_evaluation", new=AsyncMock()
            ) as mock_single,
        ):
            results = await _run_evaluations(kb_id=1, dataset=[])

        assert results == []
        mock_single.assert_not_awaited()
        # 即使空数据集，_create_evaluation_llm 已在 finally 前调用，llm.close 仍被调用
        mock_llm.close.assert_awaited_once()


class TestRunSingleEvaluation:
    """_run_single_evaluation: RAG 检索 + 指标计算 (lines 284-308)"""

    async def test_run_single_evaluation_success(self):
        """成功: get_rag_answer + _compute_ragas_metrics → 返回含 metrics 的 dict"""
        item = {"question": "什么是AI", "ground_truth": "AI是人工智能"}
        fake_metrics = {
            "faithfulness": 0.9,
            "answer_relevancy": 0.8,
            "context_precision": 0.7,
            "context_recall": 0.6,
        }

        with (
            patch(
                "app.services.evaluation_engine.get_rag_answer",
                new=AsyncMock(return_value=("AI是人工智能", ["ctx1", "ctx2"])),
            ),
            patch(
                "app.services.evaluation_engine._compute_ragas_metrics",
                new=AsyncMock(return_value=fake_metrics),
            ),
        ):
            result = await _run_single_evaluation(kb_id=1, item=item)

        assert result["question"] == "什么是AI"
        assert result["ground_truth"] == "AI是人工智能"
        assert result["answer"] == "AI是人工智能"
        assert result["contexts"] == ["ctx1", "ctx2"]
        # metrics 被 ** 展开到结果 dict
        assert result["faithfulness"] == 0.9
        assert result["answer_relevancy"] == 0.8
        assert result["context_precision"] == 0.7
        assert result["context_recall"] == 0.6


class TestExceptBlockEdgeCases:
    """except 块边界: session 不活跃 + rollback 失败 (lines 81, 84-85, 90-94)

    修复（v0.4.0）：except 块只有一次 rollback（不再有第二次），
    异常 re-raise 后由 run_evaluation_task 的重试逻辑处理。
    """

    def test_except_block_session_inactive_skips_rollback(self):
        """session.is_active=False → 跳过 rollback"""
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)
        # 关键：session 不活跃，rollback 不应被调用
        session.is_active = False
        dataset = _fake_dataset(3)

        eval_task = evaluation_task.run_evaluation_task
        eval_task.push_request(retries=settings.TASK_MAX_RETRIES_EVALUATION)
        try:
            with (
                patch.object(evaluation_task, "get_sync_session", return_value=session),
                patch.object(evaluation_task, "_prepare_dataset", return_value=dataset),
                patch.object(
                    evaluation_task, "_run_evaluations", side_effect=RuntimeError("eval error")
                ),
            ):
                with pytest.raises(RuntimeError, match="eval error"):
                    run_evaluation_task(run_id=1)
        finally:
            eval_task.pop_request()

        assert run.status == EvaluationStatus.FAILED
        # is_active=False → rollback 被跳过
        session.rollback.assert_not_called()
        session.close.assert_called()

    def test_both_rollbacks_fail_still_returns_error(self):
        """rollback 失败 → 被内部 except 捕获，仍正常 re-raise

        修复（v0.4.0）：except 块只有一次 rollback，失败被 try-except 捕获后 re-raise。
        """
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)
        dataset = _fake_dataset(3)
        # commit: _claim_run 成功(None), _update_run_status 失败
        session.commit.side_effect = [None, RuntimeError("commit failed")]
        # rollback: 第一次 (line 83) 失败
        session.rollback.side_effect = RuntimeError("rb1 failed")

        eval_task = evaluation_task.run_evaluation_task
        eval_task.push_request(retries=settings.TASK_MAX_RETRIES_EVALUATION)
        try:
            with (
                patch.object(evaluation_task, "get_sync_session", return_value=session),
                patch.object(evaluation_task, "_prepare_dataset", return_value=dataset),
                patch.object(
                    evaluation_task, "_run_evaluations", side_effect=RuntimeError("eval error")
                ),
            ):
                with pytest.raises(RuntimeError, match="eval error"):
                    run_evaluation_task(run_id=1)
        finally:
            eval_task.pop_request()

        # rollback 失败但被捕获，run 仍被标记 FAILED（_mark_run_failed）
        assert run.status == EvaluationStatus.FAILED
        assert session.rollback.call_count == 1
        session.close.assert_called()
