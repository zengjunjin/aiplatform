"""Tests for JWT iss/aud claim validation (Task 25).

Covers:
- New access/refresh tokens contain iss="rag-platform" and aud="rag-client".
- decode_token accepts tokens with correct iss/aud.
- decode_token rejects tokens missing iss/aud (legacy tokens → BREAKING).
- decode_token rejects tokens with wrong iss.
- decode_token rejects tokens with wrong aud.
"""
import pytest
from jwt import encode

from app.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)


class TestTokenContainsIssAud:
    """新 token 必须包含正确的 iss 与 aud 声明。"""

    def test_access_token_contains_iss_and_aud(self):
        token = create_access_token("42")
        payload = decode_token(token)
        assert payload is not None
        assert payload["iss"] == settings.JWT_ISSUER
        assert payload["aud"] == settings.JWT_AUDIENCE
        assert payload["type"] == "access"
        assert payload["sub"] == "42"

    def test_refresh_token_contains_iss_and_aud(self):
        token = create_refresh_token("42")
        payload = decode_token(token)
        assert payload is not None
        assert payload["iss"] == settings.JWT_ISSUER
        assert payload["aud"] == settings.JWT_AUDIENCE
        assert payload["type"] == "refresh"
        assert payload["sub"] == "42"

    def test_access_token_includes_iat(self):
        """新 token 同时应包含 iat (签发时间)。"""
        token = create_access_token("1")
        payload = decode_token(token)
        assert payload is not None
        assert "iat" in payload


class TestRejectLegacyToken:
    """旧 token（无 iss/aud）应被拒绝 —— BREAKING 变更。"""

    def test_decode_rejects_token_without_iss_aud(self):
        """旧 token 只有 sub/exp/type，无 iss/aud → decode 返回 None。"""
        from datetime import UTC, datetime, timedelta

        legacy_payload = {
            "sub": "1",
            "exp": datetime.now(UTC) + timedelta(minutes=10),
            "type": "access",
        }
        legacy_token = encode(
            legacy_payload,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        assert decode_token(legacy_token) is None


class TestRejectWrongIssAud:
    """iss/aud 不匹配的 token 必须被拒绝。"""

    def test_decode_rejects_wrong_issuer(self):
        from datetime import UTC, datetime, timedelta

        payload = {
            "sub": "1",
            "exp": datetime.now(UTC) + timedelta(minutes=10),
            "type": "access",
            "iss": "wrong-issuer",
            "aud": settings.JWT_AUDIENCE,
        }
        token = encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        assert decode_token(token) is None

    def test_decode_rejects_wrong_audience(self):
        from datetime import UTC, datetime, timedelta

        payload = {
            "sub": "1",
            "exp": datetime.now(UTC) + timedelta(minutes=10),
            "type": "access",
            "iss": settings.JWT_ISSUER,
            "aud": "wrong-audience",
        }
        token = encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        assert decode_token(token) is None

    def test_decode_rejects_wrong_iss_and_aud(self):
        from datetime import UTC, datetime, timedelta

        payload = {
            "sub": "1",
            "exp": datetime.now(UTC) + timedelta(minutes=10),
            "type": "access",
            "iss": "wrong-issuer",
            "aud": "wrong-audience",
        }
        token = encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        assert decode_token(token) is None


class TestRoundTrip:
    """签发与解码的端到端验证。"""

    def test_access_token_with_extra_claims_round_trip(self):
        token = create_access_token(
            "99",
            extra={"role": "admin", "username": "alice"},
        )
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "99"
        assert payload["role"] == "admin"
        assert payload["username"] == "alice"
        assert payload["iss"] == settings.JWT_ISSUER
        assert payload["aud"] == settings.JWT_AUDIENCE

    def test_refresh_token_round_trip(self):
        token = create_refresh_token("7")
        payload = decode_token(token)
        assert payload is not None
        assert payload["type"] == "refresh"
        assert payload["sub"] == "7"
