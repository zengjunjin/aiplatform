"""Tests for app.services.audit_service

使用 mock async_session 测试业务逻辑，不依赖真实 PostgreSQL。
重点验证: 独立 session 写入 / 异常吞掉不影响主流程 / request 字段提取正确。
"""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from app.db.audit_log import AuditLog
from app.services import audit_service


def _make_request(client_host="127.0.0.1", user_agent="Mozilla/5.0"):
    """构造 starlette Request，包含 client.host 和 user-agent header。

    ASGI scope 中 headers 必须是 list[tuple[bytes, bytes]]。
    """
    headers = [(b"user-agent", user_agent.encode("utf-8"))] if user_agent else []
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/test",
        "headers": headers,
        "query_string": b"",
        "client": (client_host, 8000) if client_host else None,
    }
    return Request(scope)


class TestLogAudit:
    @pytest.mark.asyncio
    async def test_normal_writes_with_request_and_details(self, audit_db, audit_cm):
        req = _make_request(client_host="192.168.1.1", user_agent="TestAgent")

        with patch("app.services.audit_service.async_session", return_value=audit_cm):
            await audit_service.log_audit(
                action="login",
                user_id=1,
                request=req,
                details={"key": "value"},
                result="success",
            )

        # 验证 audit_db.add 被调用一次，且传入了 AuditLog 对象
        audit_db.add.assert_called_once()
        added_obj = audit_db.add.call_args[0][0]
        assert isinstance(added_obj, AuditLog)
        assert added_obj.user_id == 1
        assert added_obj.action == "login"
        assert added_obj.ip_address == "192.168.1.1"
        assert added_obj.user_agent == "TestAgent"
        assert added_obj.details == {"key": "value"}
        assert added_obj.result == "success"
        audit_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_request_sets_ip_and_ua_to_none(self, audit_db, audit_cm):
        with patch("app.services.audit_service.async_session", return_value=audit_cm):
            await audit_service.log_audit(
                action="logout",
                user_id=2,
                request=None,
                details=None,
                result="success",
            )

        added_obj = audit_db.add.call_args[0][0]
        assert added_obj.ip_address is None
        assert added_obj.user_agent is None
        assert added_obj.details is None

    @pytest.mark.asyncio
    async def test_request_without_client_sets_ip_to_none(self, audit_db, audit_cm):
        # request.client 为 None
        req = _make_request(client_host=None, user_agent="UA")

        with patch("app.services.audit_service.async_session", return_value=audit_cm):
            await audit_service.log_audit(
                action="api_call",
                user_id=3,
                request=req,
            )

        added_obj = audit_db.add.call_args[0][0]
        assert added_obj.ip_address is None
        assert added_obj.user_agent == "UA"

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self, audit_cm):
        """async_session 异常时, log_audit 不应抛出。"""
        audit_cm.__aenter__.side_effect = RuntimeError("DB connection failed")

        with patch("app.services.audit_service.async_session", return_value=audit_cm):
            # 不应抛异常
            await audit_service.log_audit(
                action="login",
                user_id=1,
                request=None,
            )

    @pytest.mark.asyncio
    async def test_commit_exception_does_not_propagate(self, audit_db, audit_cm):
        """commit 异常时, log_audit 不应抛出。"""
        audit_db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))

        with patch("app.services.audit_service.async_session", return_value=audit_cm):
            await audit_service.log_audit(
                action="login",
                user_id=1,
                request=None,
            )

        audit_db.add.assert_called_once()
        audit_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_default_result_is_success(self, audit_db, audit_cm):
        with patch("app.services.audit_service.async_session", return_value=audit_cm):
            await audit_service.log_audit(
                action="action_without_result",
                user_id=None,
                request=None,
                # result 未传 → 默认 "success"
            )

        added_obj = audit_db.add.call_args[0][0]
        assert added_obj.result == "success"
        assert added_obj.user_id is None

    @pytest.mark.asyncio
    async def test_independent_session_used_for_write(self, audit_db, audit_cm):
        """审计日志使用独立 session 写入, 不依赖调用方传入的会话。"""
        with patch("app.services.audit_service.async_session", return_value=audit_cm):
            await audit_service.log_audit(
                action="test",
                user_id=1,
                request=None,
            )

        # 使用 async_session 创建的独立 audit_db 进行写入
        audit_db.add.assert_called_once()
        audit_db.commit.assert_awaited_once()
