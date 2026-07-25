"""Tests for app.api.v1.evaluation - RAGAS evaluation API endpoints.

Task 6: 验证 KB 权限校验 (get_kb_for_read / get_kb_for_admin)。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import evaluation
from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.evaluation import EvaluationRun, EvaluationStatus


@pytest.fixture
def admin_user():
    u = MagicMock()
    u.id = 1
    u.role = "admin"
    return u


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def request_mock():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/evaluation/runs",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }
    return Request(scope)


def _make_run(run_id=1, kb_id=1, status=EvaluationStatus.PENDING, total_questions=10):
    run = MagicMock(spec=EvaluationRun)
    run.id = run_id
    run.knowledge_base_id = kb_id
    run.status = status
    run.metrics = None
    run.total_questions = total_questions
    run.started_at = None
    run.completed_at = None
    run.created_at = MagicMock()
    run.created_at.isoformat.return_value = "2026-01-01T00:00:00"
    run.error_message = None
    return run


class TestTriggerEvaluation:
    """Task 6 SubTask 6.1: trigger_evaluation 通过 kb_service.get_kb_for_read 校验权限"""

    @pytest.mark.asyncio
    async def test_trigger_evaluation_calls_get_kb_for_read(self, admin_user, db, request_mock):
        """trigger_evaluation 应调用 get_kb_for_read(kb_id, admin.id, db)"""
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99

        db.refresh = AsyncMock(side_effect=fake_refresh)

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()) as mock_get_kb,
            patch("app.tasks.evaluation_task.run_evaluation_task") as mock_task,
        ):
            mock_task.delay.return_value = MagicMock(id="task-1")
            result = await evaluation.trigger_evaluation(
                request=request_mock, kb_id=1, num_questions=10, db=db, admin=admin_user
            )
        mock_get_kb.assert_awaited_once_with(1, 1, db)
        # APIResponse 是 Pydantic 模型，需 model_dump() 转字典后用下标访问
        result_data = result.model_dump()["data"]
        assert result_data["run_id"] == 99
        assert result_data["task_id"] == "task-1"

    @pytest.mark.asyncio
    async def test_trigger_evaluation_uses_correct_param_order(self, admin_user, db, request_mock):
        """Task 1 SubTask 1.3: trigger_evaluation 调用 get_kb_for_read 时参数顺序必须是 (kb_id, user_id, db)

        回归测试: 旧代码错误写成 get_kb_for_read(db, kb_id, admin.id)，
        导致 db 被当作 kb_id、kb_id 被当作 user_id，权限校验失效。
        正确签名见 app.services.kb_service.get_kb_for_read(kb_id, user_id, db)。
        """
        db.add = MagicMock()
        db.commit = AsyncMock()

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99

        db.refresh = AsyncMock(side_effect=fake_refresh)

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()) as mock_get_kb,
            patch("app.tasks.evaluation_task.run_evaluation_task") as mock_task,
        ):
            mock_task.delay.return_value = MagicMock(id="task-1")
            await evaluation.trigger_evaluation(
                request=request_mock, kb_id=42, num_questions=10, db=db, admin=admin_user
            )

        # 断言: 第 1 个位置参数是 kb_id (int 42)，第 2 个是 admin.id (int 1)，第 3 个是 db
        call_args = mock_get_kb.await_args
        assert call_args.args[0] == 42, "第一个参数必须是 kb_id (int)"
        assert call_args.args[1] == 1, "第二个参数必须是 admin.id (int)"
        assert call_args.args[2] is db, "第三个参数必须是 db (AsyncSession)"
        # 防退化: 不允许 db 出现在第 1 或第 2 个位置
        assert call_args.args[0] is not db, "db 不应作为第一个参数"
        assert call_args.args[1] is not db, "db 不应作为第二个参数"

    @pytest.mark.asyncio
    async def test_trigger_evaluation_kb_not_found_raises(self, admin_user, db, request_mock):
        """KB 不存在 → NotFoundError 透传"""
        with patch(
            "app.services.kb_service.get_kb_for_read",
            new=AsyncMock(side_effect=NotFoundError("Knowledge base not found")),
        ):
            with pytest.raises(NotFoundError):
                await evaluation.trigger_evaluation(
                    request=request_mock, kb_id=999, num_questions=10, db=db, admin=admin_user
                )

    @pytest.mark.asyncio
    async def test_trigger_evaluation_no_permission_raises_forbidden(
        self, admin_user, db, request_mock
    ):
        """非 owner/协作者 → ForbiddenError 透传"""
        with patch(
            "app.services.kb_service.get_kb_for_read",
            new=AsyncMock(side_effect=ForbiddenError("Access denied")),
        ):
            with pytest.raises(ForbiddenError):
                await evaluation.trigger_evaluation(
                    request=request_mock, kb_id=1, num_questions=10, db=db, admin=admin_user
                )

    @pytest.mark.asyncio
    async def test_trigger_evaluation_does_not_use_raw_select(self):
        """Task 6: 验证 trigger_evaluation 源码不再直接 select(KnowledgeBase)"""
        import inspect

        src = inspect.getsource(evaluation.trigger_evaluation)
        # 不应直接 from app.db.knowledge_base import KnowledgeBase 后 select
        assert "select(KnowledgeBase)" not in src
        # 应使用 kb_service.get_kb_for_read
        assert "get_kb_for_read" in src


class TestDeleteEvaluationRun:
    """Task 6 SubTask 6.2: delete_evaluation_run 通过 kb_service.get_kb_for_admin 校验权限"""

    @pytest.mark.asyncio
    async def test_delete_evaluation_run_calls_get_kb_for_admin(self, admin_user, db, request_mock):
        """delete_evaluation_run 应调用 get_kb_for_admin(run.kb_id, admin.id, db)"""
        run = _make_run(run_id=5, kb_id=2)
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.kb_service.get_kb_for_admin", new=AsyncMock()
        ) as mock_get_kb_admin:
            # db.execute 会被调用 2 次：1) select run, 2) delete results
            db.execute = AsyncMock(
                side_effect=[
                    MagicMock(scalar_one_or_none=lambda: run),
                    MagicMock(),  # delete result execute
                ]
            )
            result = await evaluation.delete_evaluation_run(
                run_id=5, request=request_mock, db=db, admin=admin_user
            )
        mock_get_kb_admin.assert_awaited_once_with(2, 1, db)
        # APIResponse 是 Pydantic 模型，需 model_dump() 转字典后用下标访问
        assert result.model_dump()["data"]["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_evaluation_run_uses_correct_param_order(
        self, admin_user, db, request_mock
    ):
        """Task 1 SubTask 1.3: delete_evaluation_run 调用 get_kb_for_admin 时参数顺序必须是 (kb_id, user_id, db)

        回归测试: 旧代码错误写成 get_kb_for_admin(db, run.knowledge_base_id, admin.id)，
        导致 db 被当作 kb_id、kb_id 被当作 user_id，admin 权限校验失效（可能允许越权删除）。
        正确签名见 app.services.kb_service.get_kb_for_admin(kb_id, user_id, db)。
        """
        run = _make_run(run_id=7, kb_id=42)
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.kb_service.get_kb_for_admin", new=AsyncMock()
        ) as mock_get_kb_admin:
            db.execute = AsyncMock(
                side_effect=[
                    MagicMock(scalar_one_or_none=lambda: run),
                    MagicMock(),  # delete result execute
                ]
            )
            await evaluation.delete_evaluation_run(
                run_id=7, request=request_mock, db=db, admin=admin_user
            )

        # 断言: 第 1 个参数是 run.knowledge_base_id (int 42)，第 2 个是 admin.id (int 1)，第 3 个是 db
        call_args = mock_get_kb_admin.await_args
        assert call_args.args[0] == 42, "第一个参数必须是 run.knowledge_base_id (int)"
        assert call_args.args[1] == 1, "第二个参数必须是 admin.id (int)"
        assert call_args.args[2] is db, "第三个参数必须是 db (AsyncSession)"
        # 防退化: 不允许 db 出现在第 1 或第 2 个位置
        assert call_args.args[0] is not db, "db 不应作为第一个参数"
        assert call_args.args[1] is not db, "db 不应作为第二个参数"

    @pytest.mark.asyncio
    async def test_delete_evaluation_run_no_admin_permission_raises_forbidden(
        self, admin_user, db, request_mock
    ):
        """非 admin 协作者 → ForbiddenError 透传"""
        run = _make_run(run_id=5, kb_id=2)
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: run))

        with patch(
            "app.services.kb_service.get_kb_for_admin",
            new=AsyncMock(side_effect=ForbiddenError("Access denied: insufficient permission")),
        ):
            with pytest.raises(ForbiddenError):
                await evaluation.delete_evaluation_run(
                    run_id=5, request=request_mock, db=db, admin=admin_user
                )

    @pytest.mark.asyncio
    async def test_delete_evaluation_run_kb_not_found_raises(self, admin_user, db, request_mock):
        """KB 不存在 → NotFoundError 透传"""
        run = _make_run(run_id=5, kb_id=999)
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: run))

        with patch(
            "app.services.kb_service.get_kb_for_admin",
            new=AsyncMock(side_effect=NotFoundError("Knowledge base not found")),
        ):
            with pytest.raises(NotFoundError):
                await evaluation.delete_evaluation_run(
                    run_id=5, request=request_mock, db=db, admin=admin_user
                )

    @pytest.mark.asyncio
    async def test_delete_evaluation_run_not_found(self, admin_user, db, request_mock):
        """run_id 不存在 → NotFoundError"""
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with patch(
            "app.services.kb_service.get_kb_for_admin", new=AsyncMock()
        ) as mock_get_kb_admin:
            with pytest.raises(NotFoundError):
                await evaluation.delete_evaluation_run(
                    run_id=999, request=request_mock, db=db, admin=admin_user
                )
        # run 不存在时不应调用 KB 权限校验
        mock_get_kb_admin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_evaluation_run_does_not_skip_kb_admin_check(self):
        """Task 6: 验证 delete_evaluation_run 源码包含 get_kb_for_admin 调用"""
        import inspect

        src = inspect.getsource(evaluation.delete_evaluation_run)
        assert "get_kb_for_admin" in src
