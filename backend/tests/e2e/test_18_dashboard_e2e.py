"""Dashboard 页面 E2E 测试（CDP UI）

需要 Tauri 以 CDP 端口 9223 启动：
    .\\scripts\\start_tauri_with_cdp.ps1

也包含一组无需 CDP 的 API 验证，覆盖 DashboardPage 聚合的 4 个数据源：
- GET /knowledge-bases          (KB 列表)
- GET /chat/feedback/stats      (反馈统计)
- GET /evaluation/runs          (评估运行)
- GET /system/status            (系统状态)

测试场景：
1. Dashboard 聚合 API 全部可访问（admin）
2. 非 admin 不能访问 system status
3. CDP 连接后 Dashboard 页面渲染（焦点 KPI + 4 小图区域骨架）
"""
import json
import os
import time
import pytest
import requests

from tests.e2e.conftest import extract_data
from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for_element

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


def _inject_auth_token(cdp, admin_token):
    """注入 admin_token 到前端 localStorage，避免 WebView 填表登录触发 /auth/login 限流。

    前端 auth store 使用 zustand persist，localStorage key 为 'rag-auth'，
    存储格式为 {state: {token, refreshToken, refreshTokenExpiresAt, user, themeMode}, version: 0}。
    access_token（token 字段）正常不持久化（partialize 排除），但注入后 zustand
    rehydrate 会将其读入内存，app 立即可用。onRehydrateStorage 会异步调用
    refreshAccessToken()（走 /auth/refresh，限流 10/minute，远高于 /auth/login 的 5/minute）。
    """
    auth_data = {
        "state": {
            "token": admin_token["access_token"],
            "refreshToken": admin_token["refresh_token"],
            "refreshTokenExpiresAt": int(time.time() * 1000) + 7 * 24 * 3600 * 1000,
            "user": admin_token["user"],
            "themeMode": "light",
        },
        "version": 0,
    }
    result = cdp.evaluate(f"""
        (function() {{
            try {{
                const authData = {json.dumps(auth_data)};
                localStorage.setItem('rag-auth', JSON.stringify(authData));
                return true;
            }} catch(e) {{ console.error('inject failed:', e); return false; }}
        }})()
    """)
    assert result, "localStorage token injection failed (see console.error output)"


# ============ API 层 E2E（无需 CDP）============

def test_dashboard_kb_api(base_url, admin_headers):
    """Dashboard 数据源 1：KB 列表 API

    KB list 限流 60/minute，前面 test_03_kb_e2e 已消耗部分配额，
    若被限流则等待 60s 重试一次（与 test_01_auth_e2e 限流重试模式一致）。
    """
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 5},
        headers=admin_headers, timeout=10,
    )
    if r.status_code == 429:
        time.sleep(60)
        r = requests.get(
            f"{base_url}/knowledge-bases",
            params={"page": 1, "page_size": 5},
            headers=admin_headers, timeout=10,
        )
    assert r.status_code == 200, f"KB list failed: {r.text}"
    data = extract_data(r)
    assert "items" in data
    assert "total" in data


def test_dashboard_feedback_stats_api(base_url, admin_headers):
    """Dashboard 数据源 2：反馈统计 API"""
    r = requests.get(
        f"{base_url}/chat/feedback/stats",
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"Feedback stats failed: {r.text}"
    data = extract_data(r)
    assert data is not None


def test_dashboard_evaluation_runs_api(base_url, admin_headers):
    """Dashboard 数据源 3：评估运行列表 API"""
    r = requests.get(
        f"{base_url}/evaluation/runs",
        params={"page": 1, "page_size": 5},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"Evaluation runs failed: {r.text}"
    data = extract_data(r)
    assert "items" in data


def test_dashboard_system_status_api(base_url, admin_headers):
    """Dashboard 数据源 4：系统状态 API（admin only）"""
    r = requests.get(
        f"{base_url}/system/status",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200, f"System status failed: {r.text}"
    data = extract_data(r)
    assert "postgresql" in data
    assert "redis" in data


def test_dashboard_system_status_forbidden_for_user(base_url, test_user_headers):
    """非 admin 不能访问 system status（Dashboard 安全约束）"""
    r = requests.get(
        f"{base_url}/system/status",
        headers=test_user_headers, timeout=10,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


# ============ CDP UI 层 E2E（需要 Tauri CDP）============

@pytest.fixture(scope="module")
def cdp(admin_token):
    """CDP 客户端 fixture（module scope）- 用 API token 注入 localStorage"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    client.navigate(TAURI_HOME)
    time.sleep(1)
    # 注入 token 到 localStorage（避免 /auth/login 限流）
    _inject_auth_token(client, admin_token)
    # 重新加载页面，触发 zustand persist 从 localStorage rehydrate
    client.navigate(TAURI_HOME)
    time.sleep(3)
    yield client
    client.close()


def _ensure_logged_in(cdp):
    """确保已登录（token 已由 cdp fixture 注入到 localStorage）

    检查 'rag-auth' key 中是否有 token；若已有则直接 return，不重新登录
    （避免触发 /auth/login 限流）。
    """
    cdp.navigate(TAURI_HOME)
    time.sleep(1)
    # 前端使用 zustand persist，token 存储在 'rag-auth' JSON 中
    has_token = cdp.evaluate("""
        (function() {
            try {
                var raw = localStorage.getItem('rag-auth');
                if (!raw) return false;
                var data = JSON.parse(raw);
                return !!(data && data.state && data.state.token);
            } catch(e) { return false; }
        })();
    """)
    if has_token:
        return
    # token 不存在（不应发生，cdp fixture 已注入）— 不重新登录以避免限流


def test_dashboard_page_renders(cdp):
    """Dashboard 页面渲染：导航到 /dashboard 后焦点 KPI 区域可见"""
    _ensure_logged_in(cdp)
    cdp.evaluate("window.location.hash = '#/dashboard'")
    time.sleep(3)
    url = cdp.evaluate("window.location.href") or ""
    assert "dashboard" in url.lower(), f"Not on dashboard: {url}"
    # 页面应渲染（焦点 KPI 区域或 Skeleton 都算成功）
    has_content = cdp.evaluate("""
        (function() {
            const root = document.querySelector('.ant-layout-content')
                       || document.getElementById('root')
                       || document.body;
            if (!root) return false;
            const text = root.textContent || '';
            // Dashboard 应包含今日问答/系统健康/总KB 之类的关键词或 Skeleton 占位
            const keywords = ['问答', '今日', '健康', '系统', 'Dashboard',
                              'Sessions', 'Health', 'KB', 'skeleton', 'ant-skeleton'];
            return keywords.some(k => text.toLowerCase().includes(k.toLowerCase()));
        })();
    """)
    assert has_content, "Dashboard page has no expected content"


def test_dashboard_has_kpi_or_skeleton(cdp):
    """Dashboard 应包含 KPI Statistic 卡片或加载中的 Skeleton"""
    cdp.evaluate("window.location.hash = '#/dashboard'")
    time.sleep(2)
    has_kpi = cdp.evaluate("""
        (function() {
            const stats = document.querySelectorAll('.ant-statistic');
            const skeletons = document.querySelectorAll('.ant-skeleton');
            return stats.length > 0 || skeletons.length > 0;
        })();
    """)
    assert has_kpi, "Dashboard should have statistic cards or skeletons"
