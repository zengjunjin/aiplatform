"""Tests for app/tasks/celery_app.py

覆盖内容:
  - _route_task 按任务名前缀路由到不同队列
  - celery_app 实例配置(broker/backend/serializer/timezone/time_limit 等)
  - task_queues 4 个队列配置
  - beat_schedule 定时任务(feedback-analysis-weekly / scheduled-evaluation-daily)
  - init_eventbus / close_eventbus signal handler 的 3 个分支
  - _do_eventbus_init / _do_eventbus_close 调用 EventBus.init/close
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

# 在导入 app.tasks.celery_app 之前 mock 重依赖模块，避免 coverage 工具
# 导致 numpy C 扩展 "cannot load module more than once per process" 错误。
# 导入链: app.tasks.__init__ → document_task → retriever → qdrant_client/rank_bm25 → numpy
# celery_app 测试不需要这些模块，mock 是安全的。
for _mod in (
    "qdrant_client",
    "qdrant_client.http",
    "qdrant_client.http.exceptions",
    "qdrant_client.http.models",
    "qdrant_client.models",
    "qdrant_client.conversions",
    "qdrant_client.conversions.common",
    "qdrant_client.async_qdrant_client",
    "qdrant_client.sync_qdrant_client",
    "rank_bm25",
    "app.rag.bm25",
    "app.rag.retriever",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest
from celery.schedules import crontab

from app.config import settings
from app.tasks.celery_app import (
    _do_eventbus_close,
    _do_eventbus_init,
    _route_task,
    celery_app,
    close_eventbus,
    init_eventbus,
)


def _close_coro(coro):
    """side_effect: 关闭 coroutine 避免 'coroutine never awaited' 警告。"""
    coro.close()


# ---------- _route_task ----------
class TestRouteTask:
    """按 task name 前缀路由到不同队列"""

    @pytest.mark.parametrize(
        "name,expected_queue",
        [
            ("app.tasks.document_task.parse_document_task", "queue_parsing"),
            ("app.tasks.document_task.upload", "queue_parsing"),
            ("app.tasks.evaluation_task.run", "queue_evaluation"),
            ("app.tasks.evaluation_task.batch_eval", "queue_evaluation"),
            ("app.tasks.feedback_analysis_task.run_feedback_analysis", "queue_default"),
        ],
    )
    def test_route_by_prefix(self, name, expected_queue):
        result = _route_task(name, [], {}, {})
        assert result == {"queue": expected_queue}

    def test_unknown_task_returns_none(self):
        """不在三个前缀内的任务名 → None（Celery 默认队列）"""
        assert _route_task("app.tasks.other_task.run", [], {}, {}) is None

    def test_empty_name_returns_none(self):
        assert _route_task("", [], {}, {}) is None

    def test_accepts_extra_kwargs(self):
        """函数接受 task=None 及 **kw，不应报错"""
        result = _route_task(
            "app.tasks.document_task.x",
            [],
            {},
            {},
            task=MagicMock(),
            extra="ignored",
        )
        assert result == {"queue": "queue_parsing"}

    def test_partial_prefix_no_match(self):
        """前缀不完全匹配 → None"""
        assert _route_task("app.tasks.document_task", [], {}, {}) is None
        assert _route_task("app.tasks.document", [], {}, {}) is None


# ---------- celery_app 实例配置 ----------
class TestCeleryAppConfig:
    def test_broker_and_backend(self):
        assert celery_app.conf.broker_url == settings.CELERY_BROKER_URL
        assert celery_app.conf.result_backend == settings.CELERY_RESULT_BACKEND

    def test_serializers(self):
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.accept_content == ["json"]
        assert celery_app.conf.result_serializer == "json"

    def test_timezone(self):
        assert celery_app.conf.timezone == "Asia/Shanghai"
        assert celery_app.conf.enable_utc is True

    def test_time_limits(self):
        assert celery_app.conf.task_time_limit == 300
        assert celery_app.conf.task_soft_time_limit == 240

    def test_worker_settings(self):
        assert celery_app.conf.task_acks_late is True
        assert celery_app.conf.worker_max_tasks_per_child == 100

    def test_broker_retry_and_expires(self):
        assert celery_app.conf.broker_connection_retry_on_startup is True
        assert celery_app.conf.result_expires == 3600

    def test_reject_on_worker_lost(self):
        assert celery_app.conf.task_reject_on_worker_lost is True

    def test_task_routes_includes_route_func(self):
        """task_routes 配置中包含 _route_task"""
        assert _route_task in celery_app.conf.task_routes


# ---------- task_queues ----------
class TestTaskQueues:
    def test_four_queues_configured(self):
        queue_names = [q.name for q in celery_app.conf.task_queues]
        assert set(queue_names) == {
            "queue_parsing",
            "queue_evaluation",
            "queue_default",
            "dead_letter",
        }

    def test_default_queue(self):
        assert celery_app.conf.task_default_queue == "queue_default"


# ---------- beat_schedule ----------
class TestBeatSchedule:
    def test_feedback_analysis_weekly(self):
        sched = celery_app.conf.beat_schedule["feedback-analysis-weekly"]
        assert sched["task"] == "app.tasks.feedback_analysis_task.run_feedback_analysis"
        assert sched["options"]["expires"] == 3600
        assert isinstance(sched["schedule"], crontab)
        # 每周日凌晨 3:00
        assert sched["schedule"].hour == {3}
        assert sched["schedule"].minute == {0}
        assert sched["schedule"].day_of_week == {0}

    def test_scheduled_evaluation_daily(self):
        sched = celery_app.conf.beat_schedule["scheduled-evaluation-daily"]
        assert sched["task"] == "scheduled_evaluation_task"
        assert sched["options"]["expires"] == 3600
        assert isinstance(sched["schedule"], crontab)
        # 每日 02:00
        assert sched["schedule"].hour == {2}
        assert sched["schedule"].minute == {0}

    def test_beat_schedule_has_two_entries(self):
        assert set(celery_app.conf.beat_schedule.keys()) == {
            "feedback-analysis-weekly",
            "scheduled-evaluation-daily",
        }


# ---------- init_eventbus ----------
class TestInitEventbus:
    """worker_process_init signal handler"""

    def test_calls_do_eventbus_init_when_loop_open(self):
        """loop 未关闭 → 调用 _do_eventbus_init"""
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        mock_loop.run_until_complete.side_effect = _close_coro

        with patch("app.tasks.celery_app.asyncio.get_event_loop", return_value=mock_loop):
            with patch(
                "app.tasks.celery_app._do_eventbus_init", new_callable=AsyncMock
            ) as mock_init:
                init_eventbus()
                mock_init.assert_called_once()
                mock_loop.run_until_complete.assert_called_once()

    def test_creates_new_loop_when_closed(self):
        """loop 已关闭 → 新建 loop 并 set_event_loop"""
        closed_loop = MagicMock()
        closed_loop.is_closed.return_value = True
        new_loop = MagicMock()
        new_loop.is_closed.return_value = False
        new_loop.run_until_complete.side_effect = _close_coro

        with patch(
            "app.tasks.celery_app.asyncio.get_event_loop", return_value=closed_loop
        ):
            with patch(
                "app.tasks.celery_app.asyncio.new_event_loop", return_value=new_loop
            ) as mock_new:
                with patch("app.tasks.celery_app.asyncio.set_event_loop") as mock_set:
                    with patch(
                        "app.tasks.celery_app._do_eventbus_init", new_callable=AsyncMock
                    ):
                        init_eventbus()
                        mock_new.assert_called_once()
                        mock_set.assert_called_once_with(new_loop)
                        new_loop.run_until_complete.assert_called_once()

    def test_swallows_get_event_loop_exception_with_warning(self):
        """get_event_loop 异常 → 只 warning 不抛"""
        with patch(
            "app.tasks.celery_app.asyncio.get_event_loop",
            side_effect=RuntimeError("no loop"),
        ):
            with patch("app.tasks.celery_app.logger.warning") as mock_warn:
                # 不应抛出
                init_eventbus()
                mock_warn.assert_called_once()

    def test_swallows_run_until_complete_exception_with_warning(self):
        """run_until_complete 异常 → 只 warning 不抛"""
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False

        def _raise_after_close(coro):
            coro.close()
            raise RuntimeError("init failed")

        mock_loop.run_until_complete.side_effect = _raise_after_close

        with patch(
            "app.tasks.celery_app.asyncio.get_event_loop", return_value=mock_loop
        ):
            with patch(
                "app.tasks.celery_app._do_eventbus_init", new_callable=AsyncMock
            ):
                with patch("app.tasks.celery_app.logger.warning") as mock_warn:
                    init_eventbus()
                    mock_warn.assert_called_once()


# ---------- close_eventbus ----------
class TestCloseEventbus:
    """worker_process_shutdown signal handler"""

    def test_calls_do_eventbus_close_when_loop_open(self):
        """loop 未关闭 → 调用 _do_eventbus_close"""
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False
        mock_loop.run_until_complete.side_effect = _close_coro

        with patch(
            "app.tasks.celery_app.asyncio.get_event_loop", return_value=mock_loop
        ):
            with patch(
                "app.tasks.celery_app._do_eventbus_close", new_callable=AsyncMock
            ) as mock_close:
                close_eventbus()
                mock_close.assert_called_once()
                mock_loop.run_until_complete.assert_called_once()

    def test_skips_when_loop_closed(self):
        """loop 已关闭 → 跳过，不调用 _do_eventbus_close"""
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = True

        with patch(
            "app.tasks.celery_app.asyncio.get_event_loop", return_value=mock_loop
        ):
            with patch(
                "app.tasks.celery_app._do_eventbus_close", new_callable=AsyncMock
            ) as mock_close:
                close_eventbus()
                mock_close.assert_not_called()
                mock_loop.run_until_complete.assert_not_called()

    def test_swallows_exception_with_debug(self):
        """异常 → 只 debug 不抛"""
        with patch(
            "app.tasks.celery_app.asyncio.get_event_loop",
            side_effect=RuntimeError("no loop"),
        ):
            with patch("app.tasks.celery_app.logger.debug") as mock_debug:
                close_eventbus()
                mock_debug.assert_called_once()

    def test_swallows_run_until_complete_exception_with_debug(self):
        """run_until_complete 异常 → 只 debug 不抛"""
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False

        def _raise_after_close(coro):
            coro.close()
            raise RuntimeError("close failed")

        mock_loop.run_until_complete.side_effect = _raise_after_close

        with patch(
            "app.tasks.celery_app.asyncio.get_event_loop", return_value=mock_loop
        ):
            with patch(
                "app.tasks.celery_app._do_eventbus_close", new_callable=AsyncMock
            ):
                with patch("app.tasks.celery_app.logger.debug") as mock_debug:
                    close_eventbus()
                    mock_debug.assert_called_once()


# ---------- _do_eventbus_init / _do_eventbus_close ----------
class TestDoEventbusHelpers:
    """async 辅助函数直接调用 EventBus.init / close"""

    @pytest.mark.asyncio
    async def test_do_eventbus_init_calls_eventbus_init(self):
        with patch("app.core.events.EventBus.init", new_callable=AsyncMock) as mock_init:
            await _do_eventbus_init()
            mock_init.assert_called_once()

    @pytest.mark.asyncio
    async def test_do_eventbus_close_calls_eventbus_close(self):
        with patch(
            "app.core.events.EventBus.close", new_callable=AsyncMock
        ) as mock_close:
            await _do_eventbus_close()
            mock_close.assert_called_once()
