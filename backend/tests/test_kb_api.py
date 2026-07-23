"""Tests for app.api.v1.knowledge_bases route handlers"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.api.v1 import knowledge_bases as kb
from app.db.knowledge_base import KnowledgeBase


@pytest.fixture
def user():
    u = MagicMock()
    u.id = 1
    return u


@pytest.fixture
def db():
    return AsyncMock()


def _make_kb(kb_id=1, owner_id=1, name="my-kb", description="d"):
    k = MagicMock(spec=KnowledgeBase)
    k.id = kb_id
    k.owner_id = owner_id
    k.name = name
    k.description = description
    k.created_at = MagicMock()
    k.created_at.isoformat.return_value = "2026-01-01T00:00:00"
    k.updated_at = MagicMock()
    k.updated_at.isoformat.return_value = "2026-01-01T00:00:00"
    return k


class TestCreateKb:
    @pytest.mark.asyncio
    async def test_create_kb_returns_kb(self, user, db, request_mock):
        new_kb = _make_kb(kb_id=99, name="new")
        req = MagicMock()
        with patch("app.services.kb_service.create_kb", new=AsyncMock(return_value=new_kb)):
            result = await kb.create_kb(req=req, request=request_mock, user=user, db=db)
        assert result["data"]["id"] == 99
        assert result["data"]["name"] == "new"


class TestListKbs:
    @pytest.mark.asyncio
    async def test_list_kbs_returns_paginated(self, user, db, request_mock):
        kbs = [_make_kb(kb_id=1), _make_kb(kb_id=2)]
        with patch("app.services.kb_service.list_kbs", new=AsyncMock(return_value=(kbs, 2))):
            result = await kb.list_kbs(request=request_mock, page=1, page_size=20, user=user, db=db)
        assert result["data"]["total"] == 2
        assert len(result["data"]["items"]) == 2


class TestGetKb:
    @pytest.mark.asyncio
    async def test_get_kb_returns_kb(self, user, db, request_mock):
        existing = _make_kb(kb_id=10)
        with patch("app.services.kb_service.get_kb", new=AsyncMock(return_value=existing)):
            result = await kb.get_kb(kb_id=10, request=request_mock, user=user, db=db)
        assert result["data"]["id"] == 10


class TestUpdateKb:
    @pytest.mark.asyncio
    async def test_update_kb_returns_updated(self, user, db, request_mock):
        updated = _make_kb(kb_id=10, name="renamed")
        req = MagicMock()
        with patch("app.services.kb_service.update_kb", new=AsyncMock(return_value=updated)):
            result = await kb.update_kb(kb_id=10, req=req, request=request_mock, user=user, db=db)
        assert result["data"]["name"] == "renamed"


class TestDeleteKb:
    @pytest.mark.asyncio
    async def test_delete_kb_calls_service(self, user, db, request_mock):
        with patch("app.services.kb_service.delete_kb", new=AsyncMock()) as mock_del:
            result = await kb.delete_kb(kb_id=10, request=request_mock, user=user, db=db)
        mock_del.assert_awaited_once_with(10, 1, db)
        assert "message" in result
