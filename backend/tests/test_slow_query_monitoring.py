"""Tests for Task 26: 数据库慢查询监控.

验证:
- database.py 移除了 echo=settings.DEBUG
- 注册了 before_cursor_execute / after_cursor_execute 事件监听器
- 慢查询（>100ms）通过 loguru 输出 warning
- engine connect_args 设置了 statement_timeout=30000
- config.py 新增 DB_POOL_TIMEOUT = 10
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings


class TestSlowQueryConfig:
    """Task 26 SubTask 26.1: DB_POOL_TIMEOUT 配置项"""

    def test_db_pool_timeout_exists(self):
        assert hasattr(settings, "DB_POOL_TIMEOUT")

    def test_db_pool_timeout_default_is_10(self):
        assert settings.DB_POOL_TIMEOUT == 10


class TestDatabaseEchoRemoved:
    """Task 26 SubTask 26.2: 移除 echo=settings.DEBUG"""

    def test_database_module_does_not_pass_echo_to_engine(self):
        """create_async_engine 调用不应包含 echo= 参数"""
        import inspect
        from app import database
        src = inspect.getsource(database)
        # 截取 create_async_engine( 调用片段（到闭合括号前）
        start = src.find("engine = create_async_engine(")
        assert start != -1, "create_async_engine 调用未找到"
        end = src.find(")", start)
        engine_call = src[start:end]
        # 不应在 engine 创建调用中传 echo=
        assert "echo=" not in engine_call


class TestSlowQueryEventListener:
    """Task 26 SubTask 26.3/26.4: 慢查询事件监听器"""

    def test_event_listeners_registered_on_engine_class(self):
        """验证 before_cursor_execute / after_cursor_execute 已注册到 Engine 类"""
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
        from app.database import _after_cursor_execute, _before_cursor_execute

        # event.contains 需要 (target, event_name, fn) 三参数
        assert event.contains(Engine, "before_cursor_execute", _before_cursor_execute)
        assert event.contains(Engine, "after_cursor_execute", _after_cursor_execute)

    def test_slow_query_triggers_warning_log(self):
        """模拟慢查询回调，验证 loguru.warning 被调用"""
        from app.database import _after_cursor_execute, _before_cursor_execute

        # 构造一个 context 对象，记录 _query_start_time
        context = MagicMock()
        _before_cursor_execute(None, None, "SELECT 1", None, context, False)
        assert hasattr(context, "_query_start_time")

        # 等待超过阈值
        time.sleep(0.15)  # 150ms > 100ms 阈值

        # patch loguru.logger.warning 验证慢查询日志
        with patch("app.database.logger") as mock_logger:
            _after_cursor_execute(None, None, "SELECT 1", None, context, False)
            mock_logger.warning.assert_called_once()
            args = mock_logger.warning.call_args.args[0]
            assert "Slow query" in args
            assert "SELECT 1" in args

    def test_fast_query_does_not_trigger_warning(self):
        """快速查询不应触发 warning"""
        from app.database import _after_cursor_execute, _before_cursor_execute

        context = MagicMock()
        _before_cursor_execute(None, None, "SELECT 1", None, context, False)
        # 不等待，立即调用 after
        with patch("app.database.logger") as mock_logger:
            _after_cursor_execute(None, None, "SELECT 1", None, context, False)
            mock_logger.warning.assert_not_called()


class TestStatementTimeout:
    """Task 26 SubTask 26.5: engine connect_args 设置 statement_timeout"""

    def test_engine_has_statement_timeout(self):
        """验证 async engine 的 connect_args 包含 statement_timeout=30000"""
        import inspect
        from app import database
        src = inspect.getsource(database)
        assert "statement_timeout" in src
        assert "30000" in src

    def test_engine_pool_timeout_set(self):
        """验证 engine 创建时传入了 pool_timeout=settings.DB_POOL_TIMEOUT"""
        import inspect
        from app import database
        src = inspect.getsource(database)
        assert "pool_timeout=settings.DB_POOL_TIMEOUT" in src


class TestSyncEngineAlsoListens:
    """Task 26: sync_engine 也应被慢查询监听器覆盖（监听 Engine 类即可）"""

    def test_sync_engine_event_listeners_registered(self):
        """验证 sync_engine 实例也注册了慢查询回调（监听 Engine 类即覆盖所有实例）"""
        from sqlalchemy import event
        from sqlalchemy.engine import Engine
        from app.database import _after_cursor_execute, _before_cursor_execute

        # 由于监听的是 Engine 类（不是实例），所有 Engine 实例（包括 sync_engine）
        # 上的事件都会被分发到回调
        assert event.contains(Engine, "before_cursor_execute", _before_cursor_execute)
        assert event.contains(Engine, "after_cursor_execute", _after_cursor_execute)
