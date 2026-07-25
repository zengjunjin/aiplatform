"""Tests for Pydantic schema strict mode (Task 26).

验证所有输入 Schema 启用了 extra='forbid' 严格模式,
任何额外字段都应被拒绝,防止客户端注入未声明的字段。

覆盖范围:
- auth.py: RegisterRequest, LoginRequest, RefreshRequest, ChangePasswordRequest
- user.py: UpdateRoleRequest, UpdateStatusRequest
- kb.py: KBCreate, KBUpdate, CollaboratorAdd
- chat.py: SessionCreate, SessionUpdate, MessageCreate
- feedback.py: FeedbackCreate
- document.py: DocumentUpdate
"""

import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
)
from app.schemas.chat import MessageCreate, SessionCreate, SessionUpdate
from app.schemas.document import DocumentUpdate
from app.schemas.feedback import FeedbackCreate
from app.schemas.kb import CollaboratorAdd, KBCreate, KBUpdate
from app.schemas.user import UpdateRoleRequest, UpdateStatusRequest


# ------------------------------------------------------------------
# auth.py
# ------------------------------------------------------------------
def test_register_request_rejects_extra_field():
    with pytest.raises(ValidationError):
        RegisterRequest(
            username="alice",
            email="alice@example.com",
            password="secret123",
            extra_field="bad",
        )


def test_login_request_rejects_extra_field():
    with pytest.raises(ValidationError):
        LoginRequest(username="alice", password="secret123", extra_field="bad")


def test_refresh_request_rejects_extra_field():
    with pytest.raises(ValidationError):
        RefreshRequest(refresh_token="token", extra_field="bad")


def test_change_password_request_rejects_extra_field():
    with pytest.raises(ValidationError):
        ChangePasswordRequest(
            old_password="old",
            new_password="newpass123",
            confirm_password="newpass123",
            extra_field="bad",
        )


# ------------------------------------------------------------------
# user.py
# ------------------------------------------------------------------
def test_update_role_request_rejects_extra_field():
    with pytest.raises(ValidationError):
        UpdateRoleRequest(role="admin", extra_field="bad")


def test_update_status_request_rejects_extra_field():
    with pytest.raises(ValidationError):
        UpdateStatusRequest(is_active=True, extra_field="bad")


# ------------------------------------------------------------------
# kb.py
# ------------------------------------------------------------------
def test_kb_create_rejects_extra_field():
    with pytest.raises(ValidationError):
        KBCreate(name="my-kb", extra_field="bad")


def test_kb_update_rejects_extra_field():
    with pytest.raises(ValidationError):
        KBUpdate(name="new-name", extra_field="bad")


def test_collaborator_add_rejects_extra_field():
    with pytest.raises(ValidationError):
        CollaboratorAdd(user_id=1, extra_field="bad")


# ------------------------------------------------------------------
# chat.py
# ------------------------------------------------------------------
def test_session_create_rejects_extra_field():
    with pytest.raises(ValidationError):
        SessionCreate(kb_id=1, extra_field="bad")


def test_session_update_rejects_extra_field():
    with pytest.raises(ValidationError):
        SessionUpdate(title="new-title", extra_field="bad")


def test_message_create_rejects_extra_field():
    with pytest.raises(ValidationError):
        MessageCreate(content="hello", extra_field="bad")


# ------------------------------------------------------------------
# feedback.py
# ------------------------------------------------------------------
def test_feedback_create_rejects_extra_field():
    with pytest.raises(ValidationError):
        FeedbackCreate(rating=1, extra_field="bad")


# ------------------------------------------------------------------
# document.py
# ------------------------------------------------------------------
def test_document_update_rejects_extra_field():
    with pytest.raises(ValidationError):
        DocumentUpdate(title="new-title", extra_field="bad")


# ------------------------------------------------------------------
# 正向用例:正常字段仍可正常构造
# ------------------------------------------------------------------
def test_register_request_valid_input():
    req = RegisterRequest(username="alice", email="alice@example.com", password="secret123")
    assert req.username == "alice"


def test_kb_create_valid_input():
    kb = KBCreate(name="my-kb", description="d")
    assert kb.name == "my-kb"


def test_message_create_valid_input():
    msg = MessageCreate(content="hello", model="openai")
    assert msg.content == "hello"
    assert msg.model == "openai"


def test_collaborator_add_default_permission():
    c = CollaboratorAdd(user_id=1)
    assert c.permission == "read"
