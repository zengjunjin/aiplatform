"""E2E 测试用 HTTP API 客户端封装"""

import time

import requests


class ApiClient:
    """封装常用 API 调用，自动处理 token 与重试"""

    def __init__(self, base_url: str, access_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        if access_token:
            self.session.headers["Authorization"] = f"Bearer {access_token}"

    def login(self, username: str, password: str) -> dict:
        r = self.session.post(
            f"{self.base_url}/auth/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        self.session.headers["Authorization"] = f"Bearer {data['access_token']}"
        return data

    def refresh(self, refresh_token: str) -> requests.Response:
        r = self.session.post(
            f"{self.base_url}/auth/refresh", json={"refresh_token": refresh_token}, timeout=10
        )
        return r

    def get(self, path: str, **kwargs) -> requests.Response:
        return self._retry("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        return self._retry("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> requests.Response:
        return self._retry("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self._retry("DELETE", path, **kwargs)

    def upload_file(
        self, path: str, file_path: str, field_name: str = "file", extra_data: dict = None
    ) -> requests.Response:
        with open(file_path, "rb") as f:
            files = {field_name: f}
            data = extra_data or {}
            return self.post(path, files=files, data=data, timeout=60)

    def _retry(self, method: str, path: str, retries: int = 2, **kwargs):
        """网络错误自动重试"""
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        kwargs.setdefault("timeout", 30)
        last_exc = None
        for i in range(retries + 1):
            try:
                return self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                time.sleep(1 * (i + 1))
        raise last_exc
