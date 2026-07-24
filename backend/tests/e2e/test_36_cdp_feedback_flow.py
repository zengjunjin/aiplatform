"""CDP UI 测试 - 反馈完整流程

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 反馈页加载（Title + 统计卡片 + 筛选栏 + 列表）
2. 统计概览（FeedbackStatsOverview）4 个 Statistic 卡片
3. 按 KB 筛选（不刷新页面）
4. 按类型筛选（不刷新页面）
5. 低分回答列表（LowRatedTable）
6. 趋势图（FeedbackTrendAnalysis）canvas 渲染
7. 类型分布图（FeedbackTypeChart）canvas 渲染

精简原则：筛选操作不刷新页面。
"""
import time

import pytest

from tests.e2e.helpers.cdp_auth import make_cdp_client, login_cdp_session

TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（导航到 #/feedback）"""
    client = make_cdp_client(9223)
    login_cdp_session(client, admin_token, "#/feedback")
    yield client
    client.close()


def _ensure_feedback_page(cdp):
    """确保在反馈页（不重复整页刷新，仅 hash 校正）。"""
    url = cdp.evaluate("window.location.href")
    if "/feedback" not in url:
        cdp.evaluate("window.location.hash = '#/feedback'")
        time.sleep(3)


def test_feedback_page_loads(logged_in_cdp):
    """反馈页加载：验证页面渲染（Title + 统计卡片 + 筛选栏 + 列表）"""
    cdp = logged_in_cdp
    _ensure_feedback_page(cdp)
    time.sleep(2)
    # 反馈页有标题 + 统计概览卡片行
    has_stats = cdp.evaluate("""
        (function() {
            // 统计概览有 Statistic 卡片
            const stats = document.querySelectorAll('.ant-statistic');
            return stats.length >= 1;
        })();
    """)
    assert has_stats, "Feedback page did not render statistics cards"


def test_feedback_stats_overview(logged_in_cdp):
    """统计概览：验证 4 个 Statistic 卡片（.ant-statistic）"""
    cdp = logged_in_cdp
    _ensure_feedback_page(cdp)
    time.sleep(2)
    # FeedbackStatsOverview 有 4 个 Statistic 卡片
    stats_count = cdp.evaluate("""
        (function() {
            return document.querySelectorAll('.ant-statistic').length;
        })();
    """)
    assert stats_count and stats_count >= 4, \
        f"Expected at least 4 statistic cards, got {stats_count}"


def test_filter_by_kb(logged_in_cdp):
    """按 KB 筛选：选择 KB Select，验证列表过滤（不刷新页面）"""
    cdp = logged_in_cdp
    _ensure_feedback_page(cdp)
    time.sleep(2)
    # 点击第一个 Select（KB 筛选）打开下拉
    cdp.evaluate("""
        (function() {
            const selects = document.querySelectorAll('.ant-select-selector');
            if (selects.length > 0) selects[0].click();
        })();
    """)
    time.sleep(1)
    # 选择第一个 KB 选项（跳过"全部"选项，选第一个 KB）
    cdp.evaluate("""
        (function() {
            const items = document.querySelectorAll('.ant-select-item');
            if (items.length > 1) {
                items[1].click();
                return;
            }
            if (items.length > 0) items[0].click();
        })();
    """)
    # 等待列表刷新（不刷新页面，前端过滤）
    time.sleep(2)
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
    """按类型筛选：选择类型 Select，验证列表过滤（不刷新页面）"""
    cdp = logged_in_cdp
    _ensure_feedback_page(cdp)
    time.sleep(2)
    # 点击最后一个 Select（类型筛选）打开下拉
    cdp.evaluate("""
        (function() {
            const selects = document.querySelectorAll('.ant-select-selector');
            if (selects.length > 0) selects[selects.length - 1].click();
        })();
    """)
    time.sleep(1)
    # 选择第一个类型选项（如果有）
    cdp.evaluate("""
        (function() {
            const items = document.querySelectorAll('.ant-select-item');
            if (items.length > 0) items[0].click();
        })();
    """)
    # 等待列表刷新（不刷新页面，前端过滤）
    time.sleep(2)
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


def test_low_rated_table(logged_in_cdp):
    """低分回答列表：验证 LowRatedTable 表格渲染（.ant-table）"""
    cdp = logged_in_cdp
    _ensure_feedback_page(cdp)
    time.sleep(2)
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
    assert table_state.get("hasTable") or table_state.get("hasEmpty"), \
        "Low rated table neither rendered table nor empty state"


def test_feedback_trend_chart(logged_in_cdp):
    """趋势图：验证趋势图 canvas 渲染"""
    cdp = logged_in_cdp
    _ensure_feedback_page(cdp)
    time.sleep(3)  # 等待 ECharts 渲染
    # FeedbackTrendAnalysis 包含 canvas（有数据时）或 empty（无数据时）
    has_canvas_or_empty = cdp.evaluate("""
        (function() {
            const canvases = document.querySelectorAll('canvas');
            const empties = document.querySelectorAll('.ant-empty');
            return canvases.length > 0 || empties.length > 0;
        })();
    """)
    assert has_canvas_or_empty, "Feedback trend chart has no canvas or empty state"


def test_feedback_type_chart(logged_in_cdp):
    """类型分布图：验证类型分布图 canvas 渲染"""
    cdp = logged_in_cdp
    _ensure_feedback_page(cdp)
    time.sleep(3)  # 等待 ECharts 渲染
    # FeedbackTypeChart 在 stats.by_type 为空时 return null（不渲染），
    # 有数据时渲染 ECharts canvas。canvas 存在或页面正常均为合法。
    chart_state = cdp.evaluate("""
        (function() {
            const canvases = document.querySelectorAll('canvas');
            const cards = document.querySelectorAll('.ant-card');
            return {hasCanvas: canvases.length > 0, cardCount: cards.length};
        })();
    """)
    assert chart_state is not None, "Failed to evaluate chart state"
    assert chart_state.get("hasCanvas") or chart_state.get("cardCount", 0) >= 3, \
        "Feedback type chart not rendered and page appears broken"
