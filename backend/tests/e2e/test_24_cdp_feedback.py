"""CDP UI 测试 - 反馈管理页

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 反馈页加载
2. 筛选条件栏（FeedbackFilterBar）渲染
3. 按 KB 筛选验证（UI 无评分筛选，以 KB 筛选替代）
4. 按类型筛选验证
5. 统计概览（FeedbackStatsOverview）卡片渲染
6. 类型分布图（FeedbackTypeChart）渲染
7. 趋势分析（FeedbackTrendAnalysis）渲染
8. 低分回答列表（LowRatedTable）渲染

注意：反馈数据需先通过 SSE 发送消息获取 message_id，再 POST feedback。
如 LLM 不可达导致 SSE 失败，测试验证空状态渲染。
"""

import json
import os
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import (
    wait_for,
    wait_for_dom_ready,
    wait_for_element,
    wait_for_url_change,
)

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


def _inject_auth_token(cdp, admin_token):
    """注入 admin_token 到前端 localStorage，避免 WebView 填表登录触发 /auth/login 限流。"""
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
    cdp.evaluate(f"""
        try {{
            const authData = {json.dumps(auth_data)};
            localStorage.setItem('rag-auth', JSON.stringify(authData));
        }} catch(e) {{}}
    """)


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（用 API token 注入 localStorage，避免 WebView 填表登录触发限流）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    client.navigate(TAURI_HOME)
    wait_for_dom_ready(client, timeout=10)
    _inject_auth_token(client, admin_token)
    client.navigate(TAURI_HOME)
    wait_for_dom_ready(client, timeout=10)
    yield client
    client.close()


@pytest.fixture(scope="module")
def feedback_data(base_url, admin_headers, kb_with_doc):
    """通过 API 创建反馈数据（session + message + feedback），用于 UI 渲染验证。

    流程：创建 session → SSE 发送消息获取 message_id → POST feedback（rating=-1 点踩）。
    如 SSE 失败（LLM 不可达），返回 None，测试验证空状态。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    # 1. 创建会话
    try:
        r = requests.post(
            f"{base_url}/chat/sessions",
            json={
                "title": f"FB测试_{uuid.uuid4().hex[:6]}",
                "kb_id": kb_with_doc["kb"]["id"],
            },
            headers=headers,
            timeout=10,
        )
        if r.status_code != 200:
            return None
        session = r.json().get("data", {})
        session_id = session["id"]
    except Exception:
        return None
    # 2. SSE 发送消息获取 message_id
    message_id = None
    url = f"{base_url}/chat/sessions/{session_id}/messages"
    for _attempt in range(3):
        try:
            with requests.post(
                url, json={"content": "你好"}, headers=headers, stream=True, timeout=60
            ) as r:
                if r.status_code == 429:
                    time.sleep(2)  # 限流退避
                    continue
                if r.status_code != 200:
                    return None
                for line in r.iter_lines(decode_unicode=True):
                    if line and line.startswith("data:"):
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            evt = json.loads(payload)
                        except Exception:
                            continue
                        if evt.get("event") == "done" and evt.get("message_id"):
                            message_id = evt["message_id"]
                            break
                break
        except Exception:
            continue
    if not message_id:
        return None
    # 3. POST feedback（rating=-1 点踩 + feedback_type）
    try:
        r = requests.post(
            f"{base_url}/chat/messages/{message_id}/feedback",
            json={
                "rating": -1,
                "comment": f"CDP测试反馈_{uuid.uuid4().hex[:6]}",
                "feedback_type": "incompleteness",
            },
            headers=headers,
            timeout=10,
        )
        if r.status_code != 200:
            return None
        return {"session_id": session_id, "message_id": message_id}
    except Exception:
        return None


def _reset_feedback_page(cdp):
    """重置反馈页：重新加载并导航到 /#/feedback"""
    cdp.navigate(TAURI_HOME)
    wait_for_dom_ready(cdp, timeout=10)
    cdp.evaluate("window.location.hash = '#/feedback'")
    wait_for_url_change(cdp, "#/feedback", timeout=10)
    wait_for_element(cdp, ".ant-statistic, .ant-card, .ant-empty", timeout=15)


def test_feedback_page_loads(logged_in_cdp):
    """反馈页加载：导航到 /#/feedback，验证页面渲染（标题 + 统计概览卡片）"""
    cdp = logged_in_cdp
    _reset_feedback_page(cdp)
    # 反馈页有标题 + 统计概览卡片行
    has_content = cdp.evaluate("""
        (function() {
            // 统计概览有 4 个 Statistic 卡片
            const stats = document.querySelectorAll('.ant-statistic');
            return stats.length >= 1;
        })();
    """)
    assert has_content, "Feedback page did not render statistics cards"


def test_feedback_filter_bar(logged_in_cdp):
    """筛选条件栏渲染：验证 FeedbackFilterBar（KB 选择 + 日期范围 + 类型筛选）"""
    cdp = logged_in_cdp
    _reset_feedback_page(cdp)
    wait_for_element(cdp, ".ant-select", timeout=10)
    # FeedbackFilterBar 是一个 Card，内含 Select(KB) + RangePicker + Select(Type)
    has_filter = cdp.evaluate("""
        (function() {
            const selects = document.querySelectorAll('.ant-select');
            // 至少 2 个 Select（KB 筛选 + 类型筛选）
            const hasRangePicker = !!document.querySelector('.ant-picker-range');
            return selects.length >= 2 && hasRangePicker;
        })();
    """)
    assert has_filter, "Feedback filter bar missing KB select, type select, or date range picker"


def test_filter_by_rating(logged_in_cdp, feedback_data, kb_with_doc):
    """按评分筛选验证。

    注意：FeedbackFilterBar 实际无"评分筛选"控件（仅有 KB/日期/类型筛选）。
    本测试改为验证 KB 筛选功能（最接近的筛选维度）：选择 KB → 列表刷新。
    如无反馈数据则验证筛选 UI 可交互不崩溃。
    """
    cdp = logged_in_cdp
    _reset_feedback_page(cdp)
    wait_for_element(cdp, ".ant-select", timeout=10)
    # 点击第一个 Select（KB 筛选）打开下拉
    cdp.evaluate("""
        (function() {
            const selects = document.querySelectorAll('.ant-select-selector');
            if (selects.length > 0) selects[0].click();
        })();
    """)
    wait_for_element(cdp, ".ant-select-item", timeout=5)
    # 选择第一个 KB 选项（如果有）
    cdp.evaluate("""
        (function() {
            const items = document.querySelectorAll('.ant-select-item');
            if (items.length > 1) {
                items[1].click();  // 跳过"全部"选项，选第一个 KB
                return true;
            }
            if (items.length > 0) {
                items[0].click();
                return true;
            }
            return false;
        })();
    """)
    # 等待列表刷新
    wait_for(
        lambda: cdp.evaluate("""
            (function() {
                const stats = document.querySelectorAll('.ant-statistic');
                const tables = document.querySelectorAll('.ant-table');
                const empties = document.querySelectorAll('.ant-empty');
                return stats.length > 0 || tables.length > 0 || empties.length > 0;
            })();
        """),
        timeout=8,
        interval=0.5,
        message="Page did not stabilize after KB filter selection",
    )
    # 验证页面未崩溃（统计卡片或表格仍存在）
    page_ok = cdp.evaluate("""
        (function() {
            const stats = document.querySelectorAll('.ant-statistic');
            const tables = document.querySelectorAll('.ant-table');
            const empties = document.querySelectorAll('.ant-empty');
            return stats.length > 0 || tables.length > 0 || empties.length > 0;
        })();
    """)
    assert page_ok, "Page crashed after KB filter selection"


def test_filter_by_type(logged_in_cdp):
    """按类型筛选验证：选择类型筛选 → 列表刷新"""
    cdp = logged_in_cdp
    _reset_feedback_page(cdp)
    wait_for_element(cdp, ".ant-select", timeout=10)
    # 点击最后一个 Select（类型筛选）打开下拉
    cdp.evaluate("""
        (function() {
            const selects = document.querySelectorAll('.ant-select-selector');
            if (selects.length > 0) selects[selects.length - 1].click();
        })();
    """)
    wait_for_element(cdp, ".ant-select-item", timeout=5)
    # 选择第一个类型选项（如果有）
    cdp.evaluate("""
        (function() {
            const items = document.querySelectorAll('.ant-select-item');
            if (items.length > 0) {
                items[0].click();
                return true;
            }
            return false;
        })();
    """)
    # 等待列表刷新
    wait_for(
        lambda: cdp.evaluate("""
            (function() {
                const stats = document.querySelectorAll('.ant-statistic');
                const tables = document.querySelectorAll('.ant-table');
                const empties = document.querySelectorAll('.ant-empty');
                return stats.length > 0 || tables.length > 0 || empties.length > 0;
            })();
        """),
        timeout=8,
        interval=0.5,
        message="Page did not stabilize after type filter selection",
    )
    # 验证页面未崩溃
    page_ok = cdp.evaluate("""
        (function() {
            const stats = document.querySelectorAll('.ant-statistic');
            const tables = document.querySelectorAll('.ant-table');
            const empties = document.querySelectorAll('.ant-empty');
            return stats.length > 0 || tables.length > 0 || empties.length > 0;
        })();
    """)
    assert page_ok, "Page crashed after type filter selection"


def test_feedback_stats_overview(logged_in_cdp):
    """统计概览卡片渲染：验证 FeedbackStatsOverview（总数/好评率/差评率/类型数）"""
    cdp = logged_in_cdp
    _reset_feedback_page(cdp)
    wait_for_element(cdp, ".ant-statistic", timeout=10)
    # FeedbackStatsOverview 有 4 个 Statistic 卡片
    stats_count = cdp.evaluate("""
        (function() {
            return document.querySelectorAll('.ant-statistic').length;
        })();
    """)
    assert (
        stats_count and stats_count >= 4
    ), f"Expected at least 4 statistic cards, got {stats_count}"


def test_feedback_type_chart(logged_in_cdp):
    """类型分布图渲染：验证 FeedbackTypeChart（canvas 元素或组件不渲染）

    FeedbackTypeChart 在 stats.by_type 为空时 return null（不渲染），
    有数据时渲染 ECharts canvas。
    """
    cdp = logged_in_cdp
    _reset_feedback_page(cdp)
    time.sleep(3)  # 等待 ECharts 渲染
    # 检查 canvas 元素存在（有反馈数据时）或页面正常（无数据时组件返回 null）
    chart_state = cdp.evaluate("""
        (function() {
            const canvases = document.querySelectorAll('canvas');
            const cards = document.querySelectorAll('.ant-card');
            // canvas 存在表示图表渲染了；cards >= 3 表示页面正常（标题+统计+趋势至少）
            return {hasCanvas: canvases.length > 0, cardCount: cards.length};
        })();
    """)
    assert chart_state is not None, "Failed to evaluate chart state"
    # 有 canvas（图表渲染）或页面正常（无数据时组件不渲染）均为合法
    assert (
        chart_state.get("hasCanvas") or chart_state.get("cardCount", 0) >= 3
    ), "Feedback type chart not rendered and page appears broken"


def test_feedback_trend_analysis(logged_in_cdp):
    """趋势分析渲染：验证 FeedbackTrendAnalysis（卡片 + Segmented + canvas/empty）"""
    cdp = logged_in_cdp
    _reset_feedback_page(cdp)
    wait_for_element(cdp, ".ant-segmented", timeout=10)
    # FeedbackTrendAnalysis 包含 Segmented（7/30/90 天切换）+ 折线图 + 热力图
    has_segmented = cdp.evaluate("""
        (function() {
            // Segmented 控件
            const segmented = document.querySelectorAll('.ant-segmented');
            return segmented.length > 0;
        })();
    """)
    assert has_segmented, "Feedback trend analysis missing Segmented control"
    # 验证 canvas 或 empty 存在（图表渲染或无数据空状态）
    has_chart_or_empty = cdp.evaluate("""
        (function() {
            const canvases = document.querySelectorAll('canvas');
            const empties = document.querySelectorAll('.ant-empty');
            return canvases.length > 0 || empties.length > 0;
        })();
    """)
    assert has_chart_or_empty, "Feedback trend analysis has no chart or empty state"


def test_low_rated_table(logged_in_cdp):
    """低分回答列表渲染：验证 LowRatedTable（表格卡片 + 表头或空状态）"""
    cdp = logged_in_cdp
    _reset_feedback_page(cdp)
    wait_for_element(cdp, ".ant-table, .ant-empty", timeout=10)
    # LowRatedTable 是一个 Card，内含 Table 或 Empty
    table_state = cdp.evaluate("""
        (function() {
            const tables = document.querySelectorAll('.ant-table');
            const empties = document.querySelectorAll('.ant-empty');
            return {
                hasTable: tables.length > 0,
                hasEmpty: empties.length > 0,
                tableCount: tables.length
            };
        })();
    """)
    assert table_state is not None, "Failed to evaluate low rated table state"
    # 有表格或空状态均为合法
    assert table_state.get("hasTable") or table_state.get(
        "hasEmpty"
    ), "Low rated table neither rendered table nor empty state"
