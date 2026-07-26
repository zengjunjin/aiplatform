"""Dashboard 与 System 页面的 API 层 + CDP UI 层 E2E 测试

包含两类测试：
1. API 层 E2E（无需 CDP）：直接请求后端 API，覆盖 DashboardPage / SystemPage
   聚合的数据源（KB 列表 / 反馈统计 / 评估运行 / 系统状态 / 模型列表 / metrics）。
2. CDP UI 层 E2E（需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行）：
   - Dashboard 加载（KPI 卡片 .ant-statistic + 图表卡片 .ant-card）
   - Dashboard KPI 数值有效（非 undefined/NaN）
   - System 页加载（5 个组件状态卡: postgresql/redis/ollama/qdrant/celery）
   - System 组件状态 Tag（healthy=green "健康" / unhealthy=red "故障"）
   - System 刷新按钮（点击后页面更新）

注意：
- DashboardPage 顶部 2 个 KPI Card（今日问答数 + 系统健康状态），
  每个含 Statistic 组件；下方 4 个图表 Card（文档趋势/评估趋势/反馈比/模型健康）。
- SystemPage 渲染 5 个组件 Card（PostgreSQL/Redis/Ollama/Qdrant/Celery），
  每个含 Statistic + Tag（green "健康" / red "故障"）。
  刷新按钮文案为"刷新"（i18n: evaluation.refresh）。
"""

import os
import time

import pytest
import requests

from tests.e2e.conftest import extract_data
from tests.e2e.helpers.cdp_auth import login_cdp_session, make_cdp_client
from tests.e2e.helpers.waiters import wait_for_element


@pytest.fixture(scope="module")
def logged_in_cdp(base_url):
    """admin 登录后的 CDP 客户端，导航到 /#/dashboard。

    使用独立 admin 登录而非共享 admin_token fixture，避免其他 CDP 测试
    中 refresh token 轮换或 logout 黑名单导致本 fixture 的 token 失效。
    admin 密码优先级：E2E_ADMIN_PASSWORD（CI secret）> INITIAL_ADMIN_PASSWORD
    （本地 .env 配置）> "admin123"（默认值）。
    H14 修复：增加 INITIAL_ADMIN_PASSWORD 回退，与 conftest.py 保持一致。
    """
    admin_password = (
        os.getenv("E2E_ADMIN_PASSWORD")
        or os.getenv("INITIAL_ADMIN_PASSWORD")
        or "admin123"
    )
    r = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": "admin",
            "password": admin_password,
        },
        timeout=10,
    )
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    token_data = r.json().get("data", r.json())
    client = make_cdp_client(9223)
    login_cdp_session(client, token_data, "#/dashboard")
    yield client
    client.close()


# ============ API 层 E2E（无需 CDP）============


def test_dashboard_kb_api(base_url, admin_headers):
    """Dashboard 数据源 1：KB 列表 API

    KB list 限流 60/minute，前面 test_03_kb_e2e 已消耗部分配额，
    若被限流则等待 60s 重试一次（与 test_01_auth_e2e 限流重试模式一致）。
    """
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 5},
        headers=admin_headers,
        timeout=10,
    )
    if r.status_code == 429:
        time.sleep(60)
        r = requests.get(
            f"{base_url}/knowledge-bases",
            params={"page": 1, "page_size": 5},
            headers=admin_headers,
            timeout=10,
        )
    assert r.status_code == 200, f"KB list failed: {r.text}"
    data = extract_data(r)
    assert "items" in data
    assert "total" in data


def test_dashboard_feedback_stats_api(base_url, admin_headers):
    """Dashboard 数据源 2：反馈统计 API"""
    r = requests.get(
        f"{base_url}/chat/feedback/stats",
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Feedback stats failed: {r.text}"
    data = extract_data(r)
    assert data is not None


def test_dashboard_evaluation_runs_api(base_url, admin_headers):
    """Dashboard 数据源 3：评估运行列表 API"""
    r = requests.get(
        f"{base_url}/evaluation/runs",
        params={"page": 1, "page_size": 5},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Evaluation runs failed: {r.text}"
    data = extract_data(r)
    assert "items" in data


def test_dashboard_system_status_api(base_url, admin_headers):
    """Dashboard 数据源 4：系统状态 API（admin only）"""
    r = requests.get(
        f"{base_url}/system/status",
        headers=admin_headers,
        timeout=15,
    )
    assert r.status_code == 200, f"System status failed: {r.text}"
    data = extract_data(r)
    assert "postgresql" in data
    assert "redis" in data


def test_system_status_returns_all_components(base_url, admin_headers):
    """SystemPage 数据源：/system/status 应返回所有 5 个组件状态"""
    r = requests.get(
        f"{base_url}/system/status",
        headers=admin_headers,
        timeout=15,
    )
    assert r.status_code == 200, f"System status failed: {r.text}"
    data = extract_data(r)
    for component in ("postgresql", "redis", "ollama", "qdrant", "celery"):
        assert component in data, f"Missing {component} in system status"


def test_system_models_list(base_url, admin_headers):
    """SystemPage 数据源：/system/models 返回模型列表"""
    r = requests.get(
        f"{base_url}/system/models",
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"List models failed: {r.text}"
    data = extract_data(r)
    assert "models" in data
    assert isinstance(data["models"], list)


def test_system_status_forbidden(base_url, test_user_headers):
    """非 admin 不能访问 system status（Dashboard / System 页安全约束）"""
    r = requests.get(
        f"{base_url}/system/status",
        headers=test_user_headers,
        timeout=10,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"


def test_metrics_admin_ok(base_url, admin_headers):
    """SystemPage 顶部 /metrics 可访问（admin，Prometheus 格式）"""
    metrics_url = base_url.replace("/api/v1", "") + "/metrics"
    r = requests.get(metrics_url, headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"Metrics failed: {r.text}"
    assert "# HELP" in r.text or "# TYPE" in r.text, "Response is not Prometheus format"


# ============ CDP UI 层 E2E（需要 Tauri CDP）============


def test_dashboard_loads(logged_in_cdp):
    """用例1: 验证 KPI 卡片(.ant-statistic) + 图表卡片(.ant-card) 渲染。

    DashboardPage 顶部 2 个 KPI Card（含 .ant-statistic），
    下方 4 个图表 Card（含 .ant-card）。
    """
    cdp = logged_in_cdp
    wait_for_element(cdp, ".ant-statistic", timeout=20)
    # 验证 KPI Statistic 渲染
    has_statistic = cdp.evaluate("!!document.querySelector('.ant-statistic')")
    assert has_statistic, "KPI statistic (.ant-statistic) not found on dashboard"
    # 验证 Card 渲染
    has_card = cdp.evaluate("!!document.querySelector('.ant-card')")
    assert has_card, "Card (.ant-card) not found on dashboard"


def test_dashboard_kpi_values(logged_in_cdp):
    """用例2: 验证 KPI 数值不为 undefined/NaN。

    DashboardPage .ant-statistic-content-value 渲染 KPI 数值文本，
    今日问答数为数字，系统健康状态为 Tag（"健康"/"故障"）。
    """
    cdp = logged_in_cdp
    wait_for_element(cdp, ".ant-statistic", timeout=20)
    values = (
        cdp.evaluate("""
        (function() {
            const stats = document.querySelectorAll('.ant-statistic-content-value');
            return Array.from(stats).map(s => s.textContent.trim());
        })();
    """)
        or []
    )
    assert len(values) > 0, "No KPI values found on dashboard"
    for v in values:
        # Tag 渲染的"健康"/"故障"也是有效值，仅排除 undefined/NaN/空
        assert v and v != "undefined" and v != "NaN", f"Invalid KPI value: '{v}'"


def test_system_page_loads(logged_in_cdp):
    """用例3: 导航 /#/system，验证 5 个组件状态卡
    (postgresql/redis/ollama/qdrant/celery)。

    SystemPage COMPONENTS 数组定义 5 个组件，每个渲染一个 Card + Statistic。
    组件中文名: PostgreSQL/Redis/Ollama/Qdrant/Celery（i18n: system.components.*）。
    """
    cdp = logged_in_cdp
    cdp.evaluate("window.location.hash = '#/system'")
    time.sleep(3)
    wait_for_element(cdp, ".ant-card", timeout=20)
    # 验证 5 个组件名出现（i18n 中文翻译为英文组件名）
    page_text = cdp.evaluate("document.body.textContent") or ""
    components = ["PostgreSQL", "Redis", "Ollama", "Qdrant", "Celery"]
    for comp in components:
        assert comp.lower() in page_text.lower(), f"Component '{comp}' not found on system page"


def test_system_component_tags(logged_in_cdp):
    """用例4: 验证每个组件状态 Tag
    (healthy=green "健康" / unhealthy=red "故障")。

    SystemPage 每个组件 Card 的 Statistic valueRender 渲染 Tag，
    color={healthy ? 'green' : 'red'}, 文本为"健康"或"故障"
    （i18n: system.status.healthy / system.status.unhealthy）。

    H14 修复：显式导航到 /#/system，避免依赖前一个测试的页面状态。
    """
    cdp = logged_in_cdp
    cdp.evaluate("window.location.hash = '#/system'")
    time.sleep(2)
    wait_for_element(cdp, ".ant-tag", timeout=20)
    tags = (
        cdp.evaluate("""
        (function() {
            const tags = document.querySelectorAll('.ant-tag');
            return Array.from(tags).map(t => t.textContent.trim().replace(/\\s/g, ''));
        })();
    """)
        or []
    )
    # 至少有一个状态 Tag
    assert len(tags) > 0, "No status tags found on system page"
    # 验证存在"健康"或"故障"状态 Tag
    has_status_tag = any("健康" in t or "故障" in t for t in tags)
    assert has_status_tag, f"No valid status tag ('健康'/'故障') found, tags: {tags}"


def test_system_refresh(logged_in_cdp):
    """用例5: 点击"刷新"按钮，验证页面更新。

    SystemPage Title 内含"刷新"按钮（i18n: evaluation.refresh = "刷新"），
    onClick 调用 fetchStatus() 重新拉取组件状态。

    H14 修复：显式导航到 /#/system，避免依赖前一个测试的页面状态。
    """
    cdp = logged_in_cdp
    cdp.evaluate("window.location.hash = '#/system'")
    time.sleep(2)
    wait_for_element(cdp, ".ant-card", timeout=20)
    # 点击刷新按钮
    clicked = cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('刷新'));
            if (btn) { btn.click(); return true; }
            return false;
        })();
    """)
    assert clicked, "Refresh button ('刷新') not found on system page"
    time.sleep(2)
    # 验证页面仍有组件状态卡（刷新后重新渲染）
    has_card = cdp.evaluate("!!document.querySelector('.ant-card')")
    assert has_card, "Card not found after refresh, page may have broken"
    # 验证 Tag 仍存在（刷新后状态重新加载）
    has_tag = cdp.evaluate("!!document.querySelector('.ant-tag')")
    assert has_tag, "Status tag not found after refresh"
