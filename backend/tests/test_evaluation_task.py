"""Tests for app.tasks.evaluation_task.run_evaluation_task"""
from unittest.mock import MagicMock, patch

import pytest

from app.db.evaluation import EvaluationStatus
from app.tasks import evaluation_task
from app.tasks.evaluation_task import run_evaluation_task


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
        with patch.object(evaluation_task, "get_sync_session", return_value=session), \
             patch.object(evaluation_task, "_prepare_dataset", return_value=[]):

            result = run_evaluation_task(run_id=1)

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

        with patch.object(evaluation_task, "get_sync_session", return_value=session), \
             patch.object(evaluation_task, "_prepare_dataset", return_value=dataset), \
             patch.object(evaluation_task, "_run_evaluations", return_value=results), \
             patch.object(evaluation_task, "aggregate_metrics", return_value=fake_metrics):

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
        """RUNNING → FAILED: _run_evaluations 抛异常后标记 FAILED"""
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)
        dataset = _fake_dataset(3)

        with patch.object(evaluation_task, "get_sync_session", return_value=session), \
             patch.object(evaluation_task, "_prepare_dataset", return_value=dataset), \
             patch.object(evaluation_task, "_run_evaluations",
                          side_effect=RuntimeError("RAGAS evaluation failed")):

            result = run_evaluation_task(run_id=1)

        # 状态变更: PENDING → RUNNING → FAILED
        assert run.status_changes == [
            EvaluationStatus.PENDING,
            EvaluationStatus.RUNNING,
            EvaluationStatus.FAILED,
        ]
        # error_message 被设置
        assert "评估失败" in run.error_message
        # 返回 error
        assert "error" in result
        assert "评估失败" in result["error"]
        # rollback 被调用
        session.rollback.assert_called()
        # session 被关闭
        session.close.assert_called_once()


class TestCommitErrDoesNotBlock:
    def test_commit_err_does_not_block(self):
        """DB commit 失败不阻断状态更新（except 块内 commit 失败被捕获）"""
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)
        dataset = _fake_dataset(3)

        # commit 调用顺序 (_prepare_dataset 被 patch, 其 commit 不执行):
        # 1. _claim_run 中 RUNNING 后 → None (成功)
        # 2. _update_run_status 中 FAILED 后 → RuntimeError (失败，被内部 except 捕获)
        session.commit.side_effect = [None, RuntimeError("commit failed in except")]

        with patch.object(evaluation_task, "get_sync_session", return_value=session), \
             patch.object(evaluation_task, "_prepare_dataset", return_value=dataset), \
             patch.object(evaluation_task, "_run_evaluations",
                          side_effect=RuntimeError("eval error")):

            # 不应抛异常，commit 错误被内部 except 捕获
            result = run_evaluation_task(run_id=1)

        # 状态仍被设为 FAILED（在 commit 失败之前已设置）
        assert run.status == EvaluationStatus.FAILED
        assert "评估失败" in run.error_message
        # 返回 error（原始异常，非 commit 错误）
        assert "error" in result
        assert "评估失败" in result["error"]
        # rollback 被调用多次（except 块 + 内部 except 块）
        assert session.rollback.call_count >= 2
        # session 被关闭
        session.close.assert_called_once()


class TestDatasetGenerationFailureHandling:
    def test_dataset_generation_failure_handling(self):
        """dataset 生成失败（返回空）标记 run 为 FAILED"""
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)

        with patch.object(evaluation_task, "get_sync_session", return_value=session), \
             patch.object(evaluation_task, "_prepare_dataset", return_value=[]):

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
        """_prepare_dataset 抛异常时也标记 FAILED"""
        run = FakeRun(status=EvaluationStatus.PENDING)
        session = _make_mock_session(run)

        with patch.object(evaluation_task, "get_sync_session", return_value=session), \
             patch.object(evaluation_task, "_prepare_dataset",
                          side_effect=RuntimeError("DB connection lost")):

            result = run_evaluation_task(run_id=1)

        # 异常被 except 捕获，状态设为 FAILED
        assert run.status == EvaluationStatus.FAILED
        assert "评估失败" in run.error_message
        assert "error" in result
        session.close.assert_called_once()
