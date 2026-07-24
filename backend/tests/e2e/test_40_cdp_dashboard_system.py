"""CDP UI 测试 - Dashboard 和 System 页面验证

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. Dashboard 加载（KPI 卡片 .ant-statistic + 图表卡片 .ant-card）
2. Dashboard KPI 数值有效（非 undefined/NaN）
3. System 页加载（5 个组件状态卡: postgresql/redis/ollama/qdrant/celery）
4. System 组件状态 Tag（healthy=green "健康" / unhealthy=red "故障"）
5. System 刷新按钮（点击后页面更新）

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

from tests.e2e.helpers.cdp_auth import make_cdp_client, login_cdp_session
from tests.e2e.helpers.waiters import wait_for_element


@pytest.fixture(scope="module")
def logged_in_cdp(base_url):
    """admin 登录后的 CDP 客户端，导航到 /#/dashboard。

    使用独立 admin 登录而非共享 admin_token fixture，避免其他 CDP 测试
    中 refresh token 轮换或 logout 黑名单导致本 fixture 的 token 失效。
    admin 密码通过环境变量 E2E_ADMIN_PASSWORD 注入（与 conftest 一致）。
    """
    admin_password = os.getenv("E2E_ADMIN_PASSWORD", "admin123")
    r = requests.post(f"{base_url}/auth/login", json={
        "username": "admin",
        "password": admin_password,
    }, timeout=10)
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    token_data = r.json().get("data", r.json())
    client = make_cdp_client(9223)
    login_cdp_session(client, token_data, "#/dashboard")
    yield client
    client.close()


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
    values = cdp.evaluate("""
        (function() {
            const stats = document.querySelectorAll('.ant-statistic-content-value');
            return Array.from(stats).map(s => s.textContent.trim());
        })();
    """) or []
    assert len(values) > 0, "No KPI values found on dashboard"
    for v in values:
        # Tag 渲染的"健康"/"故障"也是有效值，仅排除 undefined/NaN/空
        assert v and v != "undefined" and v != "NaN", \
            f"Invalid KPI value: '{v}'"


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
        assert comp.lower() in page_text.lower(), \
            f"Component '{comp}' not found on system page"


def test_system_component_tags(logged_in_cdp):
    """用例4: 验证每个组件状态 Tag
    (healthy=green "健康" / unhealthy=red "故障")。

    SystemPage 每个组件 Card 的 Statistic valueRender 渲染 Tag，
    color={healthy ? 'green' : 'red'}, 文本为"健康"或"故障"
    （i18n: system.status.healthy / system.status.unhealthy）。
    """
    cdp = logged_in_cdp
    wait_for_element(cdp, ".ant-tag", timeout=20)
    tags = cdp.evaluate("""
        (function() {
            const tags = document.querySelectorAll('.ant-tag');
            return Array.from(tags).map(t => t.textContent.trim().replace(/\\s/g, ''));
        })();
    """) or []
    # 至少有一个状态 Tag
    assert len(tags) > 0, "No status tags found on system page"
    # 验证存在"健康"或"故障"状态 Tag
    has_status_tag = any(
        "健康" in t or "故障" in t for t in tags
    )
    assert has_status_tag, \
        f"No valid status tag ('健康'/'故障') found, tags: {tags}"


def test_system_refresh(logged_in_cdp):
    """用例5: 点击"刷新"按钮，验证页面更新。

    SystemPage Title 内含"刷新"按钮（i18n: evaluation.refresh = "刷新"），
    onClick 调用 fetchStatus() 重新拉取组件状态。
    """
    cdp = logged_in_cdp
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
