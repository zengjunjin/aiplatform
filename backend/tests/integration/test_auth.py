"""认证 API 集成测试 - 真实 PostgreSQL + Redis"""
import pytest


@pytest.fixture
def user_creds():
    return {
        "username": "testuser",
        "email": "test@example.com",
        "password": "Passw0rd!@#",
    }


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
class TestRegister:
    async def test_register_success(self, client, user_creds):
        r = await client.post("/api/v1/auth/register", json=user_creds)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["username"] == user_creds["username"]
        assert data["email"] == user_creds["email"]
        assert "id" in data
        assert "password" not in data

    async def test_register_duplicate_username(self, client, user_creds):
        await client.post("/api/v1/auth/register", json=user_creds)
        r = await client.post("/api/v1/auth/register", json=user_creds)
        assert r.status_code == 409


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
class TestLogin:
    async def test_login_success(self, client, user_creds):
        await client.post("/api/v1/auth/register", json=user_creds)
        r = await client.post("/api/v1/auth/login", json={
            "username": user_creds["username"],
            "password": user_creds["password"],
        })
        assert r.status_code == 200
        data = r.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert "user" in data
        assert data["user"]["username"] == user_creds["username"]

    async def test_login_wrong_password(self, client, user_creds):
        await client.post("/api/v1/auth/register", json=user_creds)
        r = await client.post("/api/v1/auth/login", json={
            "username": user_creds["username"],
            "password": "Wrongpass1!",
        })
        assert r.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
class TestRefresh:
    async def test_refresh_success(self, client, user_creds):
        await client.post("/api/v1/auth/register", json=user_creds)
        login_r = await client.post("/api/v1/auth/login", json={
            "username": user_creds["username"],
            "password": user_creds["password"],
        })
        refresh_token = login_r.json()["data"]["refresh_token"]

        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert r.status_code == 200
        data = r.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
class TestLogout:
    async def test_logout_success(self, client, user_creds):
        await client.post("/api/v1/auth/register", json=user_creds)
        login_r = await client.post("/api/v1/auth/login", json={
            "username": user_creds["username"],
            "password": user_creds["password"],
        })
        access_token = login_r.json()["data"]["access_token"]
        refresh_token = login_r.json()["data"]["refresh_token"]

        r = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"refresh_token": refresh_token},
        )
        assert r.status_code == 200

        r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert r2.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
class TestChangePassword:
    async def test_change_password_success(self, client, user_creds):
        await client.post("/api/v1/auth/register", json=user_creds)
        login_r = await client.post("/api/v1/auth/login", json={
            "username": user_creds["username"],
            "password": user_creds["password"],
        })
        access_token = login_r.json()["data"]["access_token"]

        new_pwd = "Newpass456!@#"
        r = await client.put(
            "/api/v1/auth/password",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"old_password": user_creds["password"], "new_password": new_pwd, "confirm_password": new_pwd},
        )
        assert r.status_code == 200

        r2 = await client.post("/api/v1/auth/login", json={
            "username": user_creds["username"],
            "password": new_pwd,
        })
        assert r2.status_code == 200

        r3 = await client.post("/api/v1/auth/login", json={
            "username": user_creds["username"],
            "password": user_creds["password"],
        })
        assert r3.status_code == 401


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
class TestMe:
    async def test_me_success(self, client, user_creds):
        await client.post("/api/v1/auth/register", json=user_creds)
        login_r = await client.post("/api/v1/auth/login", json={
            "username": user_creds["username"],
            "password": user_creds["password"],
        })
        access_token = login_r.json()["data"]["access_token"]

        r = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["username"] == user_creds["username"]
        assert data["email"] == user_creds["email"]

    async def test_me_no_token(self, client):
        r = await client.get("/api/v1/auth/me")
        assert r.status_code == 401
