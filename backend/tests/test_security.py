"""Unit tests for core.security module."""

from datetime import UTC

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_password_returns_string(self):
        result = hash_password("testpassword123")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_password_different_from_plain(self):
        pwd = "mysecretpassword"
        hashed = hash_password(pwd)
        assert hashed != pwd

    def test_hash_password_same_password_different_hash(self):
        pwd = "samepassword"
        h1 = hash_password(pwd)
        h2 = hash_password(pwd)
        assert h1 != h2  # salted

    def test_verify_password_correct(self):
        pwd = "correcthorsebatterystaple"
        hashed = hash_password(pwd)
        assert verify_password(pwd, hashed) is True

    def test_verify_password_wrong(self):
        pwd = "correctpassword"
        hashed = hash_password(pwd)
        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_empty(self):
        hashed = hash_password("test")
        assert verify_password("", hashed) is False

    def test_verify_password_invalid_hash(self):
        assert verify_password("test", "invalid_hash") is False


class TestJWT:
    def test_create_access_token(self):
        token = create_access_token("1", extra={"role": "user"})
        assert isinstance(token, str)
        assert len(token) > 50

    def test_create_refresh_token(self):
        token = create_refresh_token("1")
        assert isinstance(token, str)
        assert len(token) > 50

    def test_decode_token_valid(self):
        token = create_access_token("42", extra={"role": "admin", "username": "testuser"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_decode_token_refresh_type(self):
        token = create_refresh_token("42")
        payload = decode_token(token)
        assert payload is not None
        assert payload["type"] == "refresh"

    def test_decode_token_invalid(self):
        result = decode_token("invalid_token_string")
        assert result is None

    def test_decode_token_tampered(self):
        token = create_access_token("1")
        # 修改中间部分的 payload（第二个 segment）
        parts = token.split(".")
        assert len(parts) == 3
        # 翻转 payload 字符来篡改
        tampered_payload = parts[1][::-1]
        tampered = f"{parts[0]}.{tampered_payload}.{parts[2]}"
        result = decode_token(tampered)
        assert result is None

    def test_decode_token_expired(self):
        # 用一个已知过期的 token
        from datetime import datetime, timedelta

        import jwt

        from app.config import settings

        expired_payload = {
            "sub": "1",
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "type": "access",
        }
        expired_token = jwt.encode(
            expired_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
        )
        result = decode_token(expired_token)
        assert result is None
