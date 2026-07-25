"""Tests for app.api.v1.users route handlers (admin-only user management)"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import users
from app.db.user import User


@pytest.fixture
def admin():
    a = MagicMock(spec=User)
    a.id = 1
    a.username = "admin"
    a.email = "admin@example.com"
    a.role = "admin"
    a.is_active = True
    a.created_at = MagicMock()
    a.created_at.isoformat.return_value = "2026-01-01T00:00:00"
    return a


@pytest.fixture
def db():
    return AsyncMock()


class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users_returns_paginated(self, admin, db, request_mock, make_user):
        user_list = [make_user(user_id=2), make_user(user_id=3)]
        with patch(
            "app.services.user_service.list_users", new=AsyncMock(return_value=(user_list, 2))
        ):
            result = (
                await users.list_users(
                    request=request_mock, page=1, page_size=20, db=db, admin=admin
                )
            ).model_dump()
        assert result["data"]["total"] == 2
        assert len(result["data"]["items"]) == 2


class TestUpdateRole:
    @pytest.mark.asyncio
    async def test_update_role_returns_user(self, admin, db, request_mock, make_user):
        target = make_user(user_id=2, role="admin")
        req = MagicMock()
        req.role = "admin"
        with patch(
            "app.services.user_service.update_role", new=AsyncMock(return_value=target)
        ) as mock_upd:
            result = (
                await users.update_role(
                    user_id=2, req=req, request=request_mock, db=db, admin=admin
                )
            ).model_dump()
        mock_upd.assert_awaited_once_with(2, "admin", db, admin.id)
        assert result["data"]["role"] == "admin"


class TestUpdateStatus:
    @pytest.mark.asyncio
    async def test_update_status_returns_user(self, admin, db, request_mock, make_user):
        target = make_user(user_id=2, is_active=False)
        req = MagicMock()
        req.is_active = False
        with patch(
            "app.services.user_service.update_status", new=AsyncMock(return_value=target)
        ) as mock_upd:
            result = (
                await users.update_status(
                    user_id=2, req=req, request=request_mock, db=db, admin=admin
                )
            ).model_dump()
        mock_upd.assert_awaited_once_with(2, False, db, admin.id)
        assert result["data"]["is_active"] is False
