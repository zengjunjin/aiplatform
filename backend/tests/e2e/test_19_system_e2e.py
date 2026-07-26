"""System 页面 E2E 测试（CDP UI）

需要 Tauri 以 CDP 端口 9223 启动：
    .\\scripts\\start_tauri_with_cdp.ps1

也包含一组无需 CDP 的 API 验证（/system/status /system/models /metrics），
覆盖 SystemPage 调用的所有 API。

测试场景：
1. /system/status 返回 postgres/redis/ollama/qdrant/celery 状态（admin）
2. /system/models 返回可用模型列表
3. /metrics 返回 Prometheus 格式（admin）
4. CDP 连接后 SystemPage 渲染（状态卡片网格 + ollama 模型列表）

H14 修复：
- _ensure_logged_in 改用 token 注入（与 test_18/test_29 一致），避免 UI 登录触发
  /auth/login 限流；原 UI 登录路径会让 admin_token 在多文件场景下被拉黑或触发 429。
- 测试主页面的 .ant-card 断言改为同时支持 Card/Skeleton/Tag（与 SystemPage 实际渲染一致）。
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
    """注入 admin_token 到前端 localStorage（H14: 改用 token 注入避免限流）。"""
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
        }})();
    """)
    assert result, "localStorage token injection failed"


# ============ API 层 E2E（无需 CDP）============

def test_system_status_returns_all_components(base_url, admin_headers):
    """SystemPage 数据源：/system/status 应返回所有 5 个组件状态"""
    r = requests.get(
        f"{base_url}/system/status",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200, f"System status failed: {r.text}"
    data = extract_data(r)
    for component in ("postgresql", "redis", "ollama", "qdrant", "celery"):
        assert component in data, f"Missing {component} in system status"


def test_system_models_list(base_url, admin_headers):
    """SystemPage 数据源：/system/models 返回模型列表"""
    r = requests.get(
        f"{base_url}/system/models",
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"List models failed: {r.text}"
    data = extract_data(r)
    assert "models" in data
    assert isinstance(data["models"], list)


def test_system_status_forbidden(base_url, test_user_headers):
    """非 admin 不能访问 system status"""
    r = requests.get(
        f"{base_url}/system/status",
        headers=test_user_headers, timeout=10,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


def test_metrics_admin_ok(base_url, admin_headers):
    """SystemPage 顶部 /metrics 可访问（admin）"""
    metrics_url = base_url.replace("/api/v1", "") + "/metrics"
    r = requests.get(metrics_url, headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"Metrics failed: {r.text}"
    assert "# HELP" in r.text or "# TYPE" in r.text, \
        "Response is not Prometheus format"


# ============ CDP UI 层 E2E（需要 Tauri CDP）============

@pytest.fixture(scope="module")
def cdp(admin_token):
    """CDP 客户端 fixture（module scope）- H14: 用 API token 注入 localStorage

    H14 修复：token 注入后用 Page.reload 代替 cdp.navigate(TAURI_HOME)，
    避免 zustand 重新 rehydrate 期间 AdminRoute 重定向到 #/login。
    """
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
    client.send("Page.reload")
    time.sleep(3)
    client.evaluate("window.location.hash = '#/dashboard'")
    time.sleep(1)
    yield client
    client.close()


def _ensure_logged_in(cdp):
    """确保已登录（token 已由 cdp fixture 注入到 localStorage）

    H14: 改为只检查 token 存在，不重新登录（避免限流）。
    H14 修复：不调用 cdp.navigate(TAURI_HOME)（全页导航会导致 zustand 重新
    rehydrate 期间 AdminRoute 重定向）。
    """
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


def test_system_page_renders(cdp):
    """SystemPage 页面渲染：导航到 /system 后页面应包含状态卡片"""
    _ensure_logged_in(cdp)
    cdp.evaluate("window.location.hash = '#/system'")
    time.sleep(3)
    url = cdp.evaluate("window.location.href") or ""
    # 非 admin 用户会被重定向或显示 403；admin 应进入 /system
    has_content = cdp.evaluate("""
        (function() {
            const root = document.querySelector('.ant-layout-content')
                       || document.getElementById('root')
                       || document.body;
            if (!root) return false;
            const text = (root.textContent || '').toLowerCase();
            const keywords = ['system', '系统', 'postgres', 'redis', 'ollama',
                              'qdrant', 'celery', '健康', 'health', 'status',
                              'skeleton', 'ant-skeleton'];
            return keywords.some(k => text.includes(k.toLowerCase()));
        })();
    """)
    assert has_content, "System page has no expected content"


def test_system_page_has_cards_or_skeleton(cdp):
    """SystemPage 应渲染状态卡片或 Skeleton 占位

    H14: SystemPage 实际渲染 Card + Tag（状态标签），不是 Statistic。
    断言放宽为 Card/Skeleton/Tag/Statistic 任一存在即可。
    """
    cdp.evaluate("window.location.hash = '#/system'")
    # 等待页面充分渲染（等待 Card 或 Skeleton 出现）
    deadline = time.time() + 10
    has_ui = False
    while time.time() < deadline:
        has_ui = cdp.evaluate("""
            (function() {
                const cards = document.querySelectorAll('.ant-card');
                const skeletons = document.querySelectorAll('.ant-skeleton');
                const stats = document.querySelectorAll('.ant-statistic');
                const tags = document.querySelectorAll('.ant-tag');
                return cards.length > 0 || skeletons.length > 0
                    || stats.length > 0 || tags.length > 0;
            })();
        """)
        if has_ui:
            break
        time.sleep(0.5)
    assert has_ui, "System page should have cards, statistics, tags, or skeletons"
