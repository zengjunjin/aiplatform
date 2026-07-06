"""Tests for app.api.v1.users route handlers (admin-only user management)"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
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


def _make_user(user_id=2, username="u2", email="u2@example.com",
               role="user", is_active=True):
    u = MagicMock(spec=User)
    u.id = user_id
    u.username = username
    u.email = email
    u.role = role
    u.is_active = is_active
    u.created_at = MagicMock()
    u.created_at.isoformat.return_value = "2026-01-01T00:00:00"
    return u


class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users_returns_paginated(self, admin, db):
        user_list = [_make_user(user_id=2), _make_user(user_id=3)]
        with patch("app.services.user_service.list_users", new=AsyncMock(
            return_value=(user_list, 2)
        )):
            result = await users.list_users(page=1, page_size=20, db=db, admin=admin)
        assert result["data"]["total"] == 2
        assert len(result["data"]["items"]) == 2


class TestUpdateRole:
    @pytest.mark.asyncio
    async def test_update_role_returns_user(self, admin, db):
        target = _make_user(user_id=2, role="admin")
        req = MagicMock()
        req.role = "admin"
        with patch("app.services.user_service.update_role", new=AsyncMock(return_value=target)) as mock_upd:
            result = await users.update_role(user_id=2, req=req, db=db, admin=admin)
        mock_upd.assert_awaited_once_with(2, "admin", db, admin.id)
        assert result["data"]["role"] == "admin"


class TestUpdateStatus:
    @pytest.mark.asyncio
    async def test_update_status_returns_user(self, admin, db):
        target = _make_user(user_id=2, is_active=False)
        req = MagicMock()
        req.is_active = False
        with patch("app.services.user_service.update_status", new=AsyncMock(return_value=target)) as mock_upd:
            result = await users.update_status(user_id=2, req=req, db=db, admin=admin)
        mock_upd.assert_awaited_once_with(2, False, db, admin.id)
        assert result["data"]["is_active"] is False
