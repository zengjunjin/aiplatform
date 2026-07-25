"""Tests for app.tasks.scheduled_evaluation.scheduled_evaluation_task

测试定时评估任务的核心逻辑：
- 活跃 KB 筛选查询执行
- 单 KB 触发评估成功
- 单 KB 失败隔离（不影响其他 KB）
- owner_id 作为触发权限传递
- 空结果（无活跃 KB）正常返回
- 批量成功/失败计数正确

任务本身是同步 Celery task（内部通过 asyncio.new_event_loop 运行协程），
因此测试函数为同步，mock 掉 async_session 和 trigger_evaluation。
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.tasks import scheduled_evaluation
from app.tasks.scheduled_evaluation import scheduled_evaluation_task

# ---------- 辅助函数 ----------


def _make_session_cm(active_kbs):
    """构造 async_session() 的返回值（async context manager mock）。

    Args:
        active_kbs: result.all() 返回的列表，元素为 (kb_id, owner_id) 元组。
                    空列表表示无活跃 KB。

    Returns:
        (cm, db) 元组：
        - cm: async context manager，__aenter__ 返回 db，可被多次复用
        - db: AsyncSession mock，execute 返回 result.all()=active_kbs
    """
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = active_kbs
    db.execute = AsyncMock(return_value=result)

    cm = AsyncMock()
    cm.__aenter__.return_value = db
    cm.__aexit__.return_value = None
    return cm, db


# ---------- 空结果场景 ----------


class TestScheduledEvaluationTaskEmpty:
    def test_scheduled_evaluation_task_no_active_kbs_returns_skipped(self):
        """无活跃 KB → 返回 skipped，不触发任何评估"""
        cm, _ = _make_session_cm(active_kbs=[])

        mock_trigger = AsyncMock()
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            result = scheduled_evaluation_task()

        assert result["status"] == "skipped"
        assert result["reason"] == "no_active_kbs"
        assert result["total"] == 0
        assert result["succeeded"] == 0
        assert result["failed"] == 0
        mock_trigger.assert_not_called()


# ---------- 单 KB 场景 ----------


class TestScheduledEvaluationTaskSingleKb:
    def test_scheduled_evaluation_task_single_kb_success(self):
        """单个活跃 KB 触发评估成功 → completed, succeeded=1"""
        cm, _ = _make_session_cm(active_kbs=[(1, 100)])

        mock_trigger = AsyncMock()
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            result = scheduled_evaluation_task()

        assert result["status"] == "completed"
        assert result["total"] == 1
        assert result["succeeded"] == 1
        assert result["failed"] == 0
        mock_trigger.assert_awaited_once()

    def test_scheduled_evaluation_task_single_kb_failure_counted(self):
        """单个活跃 KB 触发失败 → completed, failed=1（异常被吞掉不抛出）"""
        cm, _ = _make_session_cm(active_kbs=[(1, 100)])

        mock_trigger = AsyncMock(side_effect=RuntimeError("trigger failed"))
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            result = scheduled_evaluation_task()

        assert result["status"] == "completed"
        assert result["total"] == 1
        assert result["succeeded"] == 0
        assert result["failed"] == 1
        mock_trigger.assert_awaited_once()


# ---------- 失败隔离场景 ----------


class TestScheduledEvaluationTaskFailureIsolation:
    def test_scheduled_evaluation_task_failure_does_not_block_other_kbs(self):
        """中间 KB 失败 → 后续 KB 仍被处理，计数正确"""
        active_kbs = [(1, 100), (2, 200), (3, 300)]
        cm, _ = _make_session_cm(active_kbs=active_kbs)

        async def _trigger_side_effect(kb_id, **kwargs):
            if kb_id == 2:
                raise RuntimeError(f"KB {kb_id} evaluation failed")

        mock_trigger = AsyncMock(side_effect=_trigger_side_effect)
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            result = scheduled_evaluation_task()

        assert result["status"] == "completed"
        assert result["total"] == 3
        assert result["succeeded"] == 2
        assert result["failed"] == 1
        # 三个 KB 都被尝试触发（失败 KB 也进入了 try）
        assert mock_trigger.await_count == 3

    def test_scheduled_evaluation_task_first_kb_failure_does_not_block_rest(self):
        """首个 KB 失败 → 后续 KB 仍正常执行"""
        active_kbs = [(1, 100), (2, 200), (3, 300)]
        cm, _ = _make_session_cm(active_kbs=active_kbs)

        async def _trigger_side_effect(kb_id, **kwargs):
            if kb_id == 1:
                raise RuntimeError(f"KB {kb_id} failed")

        mock_trigger = AsyncMock(side_effect=_trigger_side_effect)
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            result = scheduled_evaluation_task()

        assert result["succeeded"] == 2
        assert result["failed"] == 1
        assert mock_trigger.await_count == 3


# ---------- owner_id 权限传递 ----------


class TestScheduledEvaluationTaskOwnerPermission:
    def test_scheduled_evaluation_task_owner_id_passed_as_user_id(self):
        """owner_id 作为 user_id 传递给 trigger_evaluation（owner 拥有读权限）"""
        cm, _ = _make_session_cm(active_kbs=[(42, 777)])

        mock_trigger = AsyncMock()
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            scheduled_evaluation_task()

        mock_trigger.assert_awaited_once()
        _, kwargs = mock_trigger.call_args
        assert kwargs["user_id"] == 777
        assert kwargs["kb_id"] == 42

    def test_scheduled_evaluation_task_different_owners_passed_correctly(self):
        """多个 KB 不同 owner → 各自 owner_id 正确传递"""
        active_kbs = [(1, 100), (2, 200), (3, 300)]
        cm, _ = _make_session_cm(active_kbs=active_kbs)

        mock_trigger = AsyncMock()
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            scheduled_evaluation_task()

        # 按 await 顺序提取每个调用的 user_id
        owner_ids = [call.kwargs["user_id"] for call in mock_trigger.call_args_list]
        assert owner_ids == [100, 200, 300]


# ---------- 活跃 KB 筛选查询 ----------


class TestScheduledEvaluationTaskQuery:
    def test_scheduled_evaluation_task_active_kb_query_executed(self):
        """活跃 KB 筛选 SQL 正确执行（db.execute 被调用一次）"""
        cm, db = _make_session_cm(active_kbs=[(1, 100)])

        mock_trigger = AsyncMock()
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            scheduled_evaluation_task()

        # 查询阶段 execute 调用一次；trigger_evaluation 被 mock 不再调 db.execute
        db.execute.assert_called_once()


# ---------- 批量触发场景 ----------


class TestScheduledEvaluationTaskBatch:
    def test_scheduled_evaluation_task_batch_all_success(self):
        """批量 KB 全部成功 → succeeded=total, failed=0"""
        active_kbs = [(1, 100), (2, 200), (3, 300), (4, 400)]
        cm, _ = _make_session_cm(active_kbs=active_kbs)

        mock_trigger = AsyncMock()
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            result = scheduled_evaluation_task()

        assert result["status"] == "completed"
        assert result["total"] == 4
        assert result["succeeded"] == 4
        assert result["failed"] == 0
        assert mock_trigger.await_count == 4

    def test_scheduled_evaluation_task_batch_all_failure(self):
        """批量 KB 全部失败 → failed=total, succeeded=0（任务不抛异常）"""
        active_kbs = [(1, 100), (2, 200), (3, 300)]
        cm, _ = _make_session_cm(active_kbs=active_kbs)

        mock_trigger = AsyncMock(side_effect=RuntimeError("all failed"))
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            result = scheduled_evaluation_task()

        assert result["status"] == "completed"
        assert result["total"] == 3
        assert result["succeeded"] == 0
        assert result["failed"] == 3
        assert mock_trigger.await_count == 3

    def test_scheduled_evaluation_task_batch_mixed_success_failure(self):
        """批量 KB 部分成功部分失败 → 计数正确"""
        active_kbs = [(1, 100), (2, 200), (3, 300), (4, 400), (5, 500)]
        cm, _ = _make_session_cm(active_kbs=active_kbs)

        async def _trigger_side_effect(kb_id, **kwargs):
            if kb_id in (2, 4):
                raise RuntimeError(f"KB {kb_id} failed")

        mock_trigger = AsyncMock(side_effect=_trigger_side_effect)
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            result = scheduled_evaluation_task()

        assert result["status"] == "completed"
        assert result["total"] == 5
        assert result["succeeded"] == 3
        assert result["failed"] == 2
        assert mock_trigger.await_count == 5


# ---------- trigger_evaluation 参数传递 ----------


class TestScheduledEvaluationTaskParameters:
    def test_scheduled_evaluation_task_uses_default_num_questions(self):
        """num_questions 使用 DEFAULT_NUM_QUESTIONS（50）"""
        cm, _ = _make_session_cm(active_kbs=[(1, 100)])

        mock_trigger = AsyncMock()
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            scheduled_evaluation_task()

        _, kwargs = mock_trigger.call_args
        assert kwargs["num_questions"] == scheduled_evaluation.DEFAULT_NUM_QUESTIONS
        assert kwargs["num_questions"] == 50

    def test_scheduled_evaluation_task_trigger_source_is_scheduled(self):
        """trigger_source 传递为 'scheduled'（非 manual）"""
        cm, _ = _make_session_cm(active_kbs=[(1, 100)])

        mock_trigger = AsyncMock()
        with (
            patch.object(scheduled_evaluation, "async_session", return_value=cm),
            patch.object(scheduled_evaluation, "trigger_evaluation", new=mock_trigger),
        ):
            scheduled_evaluation_task()

        _, kwargs = mock_trigger.call_args
        assert kwargs["trigger_source"] == "scheduled"
