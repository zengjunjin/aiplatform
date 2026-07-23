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
"""
import os
import time
import pytest
import requests

from tests.e2e.conftest import extract_data
from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for_element

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


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
def cdp():
    """CDP 客户端 fixture（module scope）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    yield client
    client.close()


def _ensure_logged_in(cdp):
    """确保已登录（admin）"""
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    url = cdp.evaluate("window.location.href") or ""
    if "/login" in url:
        cdp.evaluate("""
            try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}
            window.location.hash = '#/login';
        """)
        time.sleep(2)
        wait_for_element(cdp, "input[type='text'], input[id*='username']", timeout=15)
        cdp.fill_input("input[type='text']:first-of-type", "admin")
        time.sleep(0.5)
        cdp.fill_input("input[type='password']", "admin123")
        time.sleep(0.5)
        cdp.evaluate("""
            (function() {
                let btn = document.querySelector('button[type="submit"]')
                       || document.querySelector('button.ant-btn-primary');
                if (!btn) {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    btn = buttons.find(b =>
                        b.textContent.includes('登录') || b.textContent.includes('Login'));
                }
                if (btn) btn.click();
            })();
        """)
        deadline = time.time() + 10
        while time.time() < deadline:
            u = cdp.evaluate("window.location.href") or ""
            if "/login" not in u:
                return
            time.sleep(0.5)


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
    """SystemPage 应渲染状态卡片或 Skeleton 占位"""
    cdp.evaluate("window.location.hash = '#/system'")
    time.sleep(2)
    has_ui = cdp.evaluate("""
        (function() {
            const cards = document.querySelectorAll('.ant-card');
            const skeletons = document.querySelectorAll('.ant-skeleton');
            const stats = document.querySelectorAll('.ant-statistic');
            return cards.length > 0 || skeletons.length > 0 || stats.length > 0;
        })();
    """)
    assert has_ui, "System page should have cards, statistics, or skeletons"
