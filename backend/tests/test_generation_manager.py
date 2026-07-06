"""Tests for app.core.generation_manager.GenerationManager"""
import pytest
import asyncio
from app.core.generation_manager import GenerationManager, generation_manager


class TestStartGeneration:
    def test_start_generation_returns_event(self):
        gm = GenerationManager()
        event = gm.start_generation(session_id=1)
        assert isinstance(event, asyncio.Event)
        assert not event.is_set()  # 初始未触发

    def test_start_generation_overwrites_existing(self):
        """重复 start 同一 session → 用新 event 覆盖旧的"""
        gm = GenerationManager()
        e1 = gm.start_generation(session_id=1)
        e2 = gm.start_generation(session_id=1)
        assert e1 is not e2
        # 内部存储的是新 event
        assert gm._stop_events[1] is e2

    def test_start_generation_increments_active_count(self):
        gm = GenerationManager()
        gm.start_generation(1)
        gm.start_generation(2)
        assert gm.active_count() == 2


class TestStopGeneration:
    def test_stop_generation_signals_event(self):
        gm = GenerationManager()
        event = gm.start_generation(session_id=1)
        assert not event.is_set()
        result = gm.stop_generation(session_id=1)
        assert result is True
        assert event.is_set()

    def test_stop_generation_returns_false_for_unknown_session(self):
        gm = GenerationManager()
        result = gm.stop_generation(session_id=999)
        assert result is False

    def test_stop_generation_idempotent(self):
        """多次 stop 同一 session → 第一次 True，后续仍 True（event 已 set）"""
        gm = GenerationManager()
        gm.start_generation(session_id=1)
        assert gm.stop_generation(session_id=1) is True
        assert gm.stop_generation(session_id=1) is True  # 仍 True，event 已存在


class TestIsStopped:
    def test_is_stopped_false_for_new_generation(self):
        gm = GenerationManager()
        gm.start_generation(session_id=1)
        assert gm.is_stopped(session_id=1) is False

    def test_is_stopped_true_after_stop(self):
        gm = GenerationManager()
        gm.start_generation(session_id=1)
        gm.stop_generation(session_id=1)
        assert gm.is_stopped(session_id=1) is True

    def test_is_stopped_false_for_unknown_session(self):
        gm = GenerationManager()
        assert gm.is_stopped(session_id=999) is False


class TestEndGeneration:
    def test_end_generation_removes_event(self):
        gm = GenerationManager()
        gm.start_generation(session_id=1)
        assert gm.active_count() == 1
        gm.end_generation(session_id=1)
        assert gm.active_count() == 0
        # 结束后再 is_stopped 应返回 False
        assert gm.is_stopped(session_id=1) is False

    def test_end_generation_unknown_session_no_error(self):
        """end_generation 不存在的 session → 不抛异常"""
        gm = GenerationManager()
        gm.end_generation(session_id=999)  # 不抛
        assert gm.active_count() == 0

    def test_end_generation_idempotent(self):
        gm = GenerationManager()
        gm.start_generation(session_id=1)
        gm.end_generation(session_id=1)
        gm.end_generation(session_id=1)  # 第二次也不抛
        assert gm.active_count() == 0


class TestActiveCount:
    def test_active_count_zero_initially(self):
        gm = GenerationManager()
        assert gm.active_count() == 0

    def test_active_count_reflects_active_generations(self):
        gm = GenerationManager()
        gm.start_generation(1)
        gm.start_generation(2)
        gm.start_generation(3)
        assert gm.active_count() == 3
        gm.end_generation(2)
        assert gm.active_count() == 2
        gm.end_generation(1)
        gm.end_generation(3)
        assert gm.active_count() == 0


class TestGenerationManagerSingleton:
    def test_singleton_exists(self):
        assert isinstance(generation_manager, GenerationManager)


class TestGenerationFlow:
    """模拟完整生成流程：start → stop → is_stopped → end"""

    def test_full_flow(self):
        gm = GenerationManager()
        # 1. 开始生成
        event = gm.start_generation(session_id=42)
        assert gm.active_count() == 1
        assert gm.is_stopped(session_id=42) is False

        # 2. 用户请求取消
        stopped = gm.stop_generation(session_id=42)
        assert stopped is True
        assert gm.is_stopped(session_id=42) is True
        assert event.is_set()

        # 3. 生成循环检测到 cancel，停止
        # 4. 清理
        gm.end_generation(session_id=42)
        assert gm.active_count() == 0

    def test_multiple_sessions_independent(self):
        """多个 session 的生成独立取消"""
        gm = GenerationManager()
        e1 = gm.start_generation(1)
        e2 = gm.start_generation(2)
        # 取消 session 1，不影响 session 2
        gm.stop_generation(1)
        assert e1.is_set()
        assert not e2.is_set()
        assert gm.is_stopped(1) is True
        assert gm.is_stopped(2) is False
