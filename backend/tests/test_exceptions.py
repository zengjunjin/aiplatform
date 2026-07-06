"""Tests for app.core.exceptions and exception handlers"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.exceptions import (
    AppException, NotFoundError, AuthError, ForbiddenError,
    ConflictError, RateLimitError, ValidationError,
    app_exception_handler, validation_exception_handler, generic_exception_handler,
)
from app.core.errors import ErrorCode


class TestExceptionHierarchy:
    def test_app_exception_default_status_code(self):
        exc = AppException(code=40001, message="custom")
        assert exc.code == 40001
        assert exc.message == "custom"
        assert exc.status_code == 400

    def test_app_exception_falls_back_to_error_message(self):
        """未提供 message → 使用 errors.py 中该 code 的默认 message"""
        exc = AppException(code=ErrorCode.AUTH_FAILED)
        assert exc.code == ErrorCode.AUTH_FAILED
        assert exc.message  # 非空

    def test_not_found_error(self):
        exc = NotFoundError()
        assert exc.code == ErrorCode.RESOURCE_NOT_FOUND
        assert exc.status_code == 404

    def test_not_found_error_custom_message(self):
        exc = NotFoundError("doc not found")
        assert exc.message == "doc not found"
        assert exc.status_code == 404

    def test_auth_error_default_code(self):
        exc = AuthError()
        assert exc.code == ErrorCode.AUTH_FAILED
        assert exc.status_code == 401

    def test_auth_error_custom_code(self):
        exc = AuthError(code=ErrorCode.TOKEN_EXPIRED)
        assert exc.code == ErrorCode.TOKEN_EXPIRED
        assert exc.status_code == 401

    def test_forbidden_error(self):
        exc = ForbiddenError()
        assert exc.code == ErrorCode.PERMISSION_DENIED
        assert exc.status_code == 403

    def test_conflict_error_default_code(self):
        exc = ConflictError()
        assert exc.code == 30001
        assert exc.status_code == 409

    def test_conflict_error_custom_code(self):
        exc = ConflictError(code=30002, message="dup")
        assert exc.code == 30002
        assert exc.message == "dup"
        assert exc.status_code == 409

    def test_rate_limit_error(self):
        exc = RateLimitError()
        assert exc.code == ErrorCode.RATE_LIMITED
        assert exc.status_code == 429

    def test_validation_error(self):
        exc = ValidationError()
        assert exc.code == ErrorCode.VALIDATION_ERROR
        assert exc.status_code == 400

    def test_all_exceptions_are_app_exception(self):
        """所有自定义异常都继承 AppException，便于统一处理"""
        for exc_cls in [NotFoundError, AuthError, ForbiddenError, ConflictError, RateLimitError, ValidationError]:
            assert issubclass(exc_cls, AppException)


class TestAppExceptionHandler:
    @pytest.mark.asyncio
    async def test_app_exception_handler_returns_json(self):
        exc = NotFoundError("doc not found")
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/api/v1/docs/1"

        response = await app_exception_handler(request, exc)
        assert response.status_code == 404
        # response.body 是 bytes
        import json
        body = json.loads(response.body)
        assert body["code"] == ErrorCode.RESOURCE_NOT_FOUND
        assert body["message"] == "doc not found"
        assert body["data"] is None

    @pytest.mark.asyncio
    async def test_app_exception_handler_preserves_status_code(self):
        exc = RateLimitError()
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/auth/login"

        response = await app_exception_handler(request, exc)
        assert response.status_code == 429


class TestValidationExceptionHandler:
    @pytest.mark.asyncio
    async def test_validation_exception_handler_formats_errors(self):
        """RequestValidationError → 拼接错误信息"""
        from fastapi.exceptions import RequestValidationError
        from fastapi import HTTPException

        # 构造一个 RequestValidationError（需要 errors 列表）
        exc = RequestValidationError(errors=[
            {"loc": ("body", "username"), "msg": "field required", "type": "value_error.missing"},
            {"loc": ("body", "password"), "msg": "too short", "type": "value_error"},
        ])
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/v1/auth/register"

        response = await validation_exception_handler(request, exc)
        assert response.status_code == 400
        import json
        body = json.loads(response.body)
        assert body["code"] == ErrorCode.VALIDATION_ERROR
        assert "username" in body["message"]
        assert "password" in body["message"]

    @pytest.mark.asyncio
    async def test_validation_exception_handler_empty_errors(self):
        """无 errors → 使用默认 message"""
        from fastapi.exceptions import RequestValidationError
        exc = RequestValidationError(errors=[])
        request = MagicMock()
        request.method = "POST"
        request.url.path = "/"

        response = await validation_exception_handler(request, exc)
        assert response.status_code == 400
        import json
        body = json.loads(response.body)
        assert body["code"] == ErrorCode.VALIDATION_ERROR


class TestGenericExceptionHandler:
    @pytest.mark.asyncio
    async def test_generic_exception_handler_returns_500(self):
        exc = RuntimeError("unexpected")
        request = MagicMock()
        request.method = "GET"
        request.url.path = "/api/v1/something"

        response = await generic_exception_handler(request, exc)
        assert response.status_code == 500
        import json
        body = json.loads(response.body)
        assert body["code"] == ErrorCode.INTERNAL_ERROR
        assert body["data"] is None
