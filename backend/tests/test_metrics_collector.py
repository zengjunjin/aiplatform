"""Tests for app.tasks.metrics_collector"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks import metrics_collector


class TestUpdateBusinessMetrics:
    @pytest.mark.asyncio
    async def test_update_business_metrics_sets_gauges(self):
        """正常情况 → 设置 TOTAL_USERS/TOTAL_DOCUMENTS/ACTIVE_SESSIONS"""
        # mock async_session 上下文
        fake_db = AsyncMock()
        # Task 35: 合并后 db.execute 第一次返回 counts 行，第二次返回 KB 分组
        counts_result = MagicMock()
        counts_result.one.return_value = MagicMock(user_count=5, doc_count=10, session_count=3)
        # db.execute 返回按 KB 分组的文档数：KB#1=4, KB#2=6
        kb_result = MagicMock()
        kb_result.all.return_value = [(1, 4), (2, 6)]
        fake_db.execute = AsyncMock(side_effect=[counts_result, kb_result])

        with patch("app.tasks.metrics_collector.async_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=fake_db)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            with (
                patch("app.tasks.metrics_collector.TOTAL_USERS") as mock_users,
                patch("app.tasks.metrics_collector.TOTAL_DOCUMENTS") as mock_docs,
                patch("app.tasks.metrics_collector.ACTIVE_SESSIONS") as mock_sessions,
                patch("app.tasks.metrics_collector.RAG_DOCUMENT_COUNT") as mock_doc_count,
            ):
                await metrics_collector.update_business_metrics()

        mock_users.set.assert_called_once_with(5)
        mock_docs.set.assert_called_once_with(10)
        mock_sessions.set.assert_called_once_with(3)
        # RAG_DOCUMENT_COUNT 按 KB 分组设置
        mock_doc_count.labels.assert_any_call(kb_id="1")
        mock_doc_count.labels.assert_any_call(kb_id="2")
        mock_doc_count.labels.return_value.set.assert_any_call(4)
        mock_doc_count.labels.return_value.set.assert_any_call(6)

    @pytest.mark.asyncio
    async def test_update_business_metrics_handles_none_count(self):
        """count 返回 None → set(0)"""
        fake_db = AsyncMock()
        # Task 35: 合并后 db.execute 第一次返回 counts（含 None），第二次返回 KB 分组
        counts_result = MagicMock()
        counts_result.one.return_value = MagicMock(
            user_count=None, doc_count=None, session_count=None
        )
        # KB 分组查询返回空列表（无文档）
        kb_result = MagicMock()
        kb_result.all.return_value = []
        fake_db.execute = AsyncMock(side_effect=[counts_result, kb_result])

        with patch("app.tasks.metrics_collector.async_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=fake_db)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            with (
                patch("app.tasks.metrics_collector.TOTAL_USERS") as mock_users,
                patch("app.tasks.metrics_collector.TOTAL_DOCUMENTS"),
                patch("app.tasks.metrics_collector.ACTIVE_SESSIONS"),
                patch("app.tasks.metrics_collector.RAG_DOCUMENT_COUNT"),
            ):
                await metrics_collector.update_business_metrics()
        mock_users.set.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_update_business_metrics_handles_exception(self):
        """DB 异常 → 不抛出，仅记录 warning"""
        with patch("app.tasks.metrics_collector.async_session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(side_effect=Exception("db down"))
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            with patch("app.tasks.metrics_collector.logger") as mock_logger:
                # 不应抛异常
                await metrics_collector.update_business_metrics()
            mock_logger.warning.assert_called_once()


class TestUpdateDbPoolMetrics:
    def test_update_db_pool_metrics_sets_gauges(self):
        """正常情况 → 设置 pool size/idle/in_use"""
        fake_pool = MagicMock()
        fake_pool.size.return_value = 10
        fake_pool.checkedin.return_value = 3
        fake_pool.checkedout.return_value = 7

        with patch("app.tasks.metrics_collector.engine") as mock_engine:
            mock_engine.pool = fake_pool
            with (
                patch("app.tasks.metrics_collector.DB_POOL_SIZE") as mock_size,
                patch("app.tasks.metrics_collector.DB_POOL_IDLE") as mock_idle,
                patch("app.tasks.metrics_collector.DB_POOL_IN_USE") as mock_inuse,
            ):
                metrics_collector.update_db_pool_metrics()

        mock_size.set.assert_called_once_with(10)
        mock_idle.set.assert_called_once_with(3)
        mock_inuse.set.assert_called_once_with(7)

    def test_update_db_pool_metrics_handles_exception(self):
        """pool 访问异常 → 不抛出，仅记录 warning"""
        with patch("app.tasks.metrics_collector.engine") as mock_engine:
            mock_engine.pool.size.side_effect = Exception("pool error")
            with patch("app.tasks.metrics_collector.logger") as mock_logger:
                # 不应抛异常
                metrics_collector.update_db_pool_metrics()
            mock_logger.warning.assert_called_once()


class TestMetricsCollectorLoop:
    @pytest.mark.asyncio
    async def test_metrics_collector_loop_runs_once_then_sleeps(self):
        """loop 至少执行一次 update 后 sleep"""
        call_count = {"business": 0, "pool": 0}

        async def fake_update_business():
            call_count["business"] += 1

        def fake_update_pool():
            call_count["pool"] += 1

        # 模拟 sleep 立即返回并中断循环
        sleep_calls = [0]

        async def fake_sleep(interval):
            sleep_calls[0] += 1
            if sleep_calls[0] >= 1:
                raise KeyboardInterrupt()  # 跳出 while True

        with (
            patch.object(
                metrics_collector, "update_business_metrics", side_effect=fake_update_business
            ),
            patch.object(metrics_collector, "update_db_pool_metrics", side_effect=fake_update_pool),
            patch("app.tasks.metrics_collector.asyncio.sleep", side_effect=fake_sleep),
        ):
            with pytest.raises(KeyboardInterrupt):
                await metrics_collector.metrics_collector_loop(interval=60)

        assert call_count["business"] == 1
        assert call_count["pool"] == 1

    @pytest.mark.asyncio
    async def test_metrics_collector_loop_handles_inner_exception(self):
        """update_business_metrics 抛异常 → loop 继续（不退出）"""
        call_count = [0]

        async def fake_update_business():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("transient error")

        sleep_count = [0]

        async def fake_sleep(interval):
            sleep_count[0] += 1
            if sleep_count[0] >= 1:
                raise KeyboardInterrupt()

        with (
            patch.object(
                metrics_collector, "update_business_metrics", side_effect=fake_update_business
            ),
            patch.object(metrics_collector, "update_db_pool_metrics"),
            patch("app.tasks.metrics_collector.asyncio.sleep", side_effect=fake_sleep),
            patch("app.tasks.metrics_collector.logger"),
        ):
            with pytest.raises(KeyboardInterrupt):
                await metrics_collector.metrics_collector_loop(interval=60)
        # 第一次抛异常但 loop 继续，sleep 后才退出
        assert call_count[0] == 1
