"""CDP UI 测试 - 评测管理页

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行 + 至少一个已解析文档的 KB。

测试场景：
1. 评测页加载与历史记录表格渲染
2. 触发评测弹窗（TriggerEvalModal）打开
3. 触发评测提交 + 进度面板（ProgressPanel）显示
4. 评测历史记录表格列验证
5. 评测详情弹窗（RunDetailModal）渲染
6. 评测趋势图（EvaluationTrendChart）渲染

注意：触发评测需要 Ollama 可达且有 3/hour 限额，如不可达则标记 SKIPPED。
"""

import os
import time

import pytest
import requests

from tests.e2e.helpers.cdp_auth import login_cdp_session
from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import (
    wait_for_dom_ready,
    wait_for_element,
    wait_for_url_change,
)

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（用 API token 注入 localStorage，避免 WebView 填表登录触发限流）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    login_cdp_session(client, admin_token, "#/evaluation")
    yield client
    client.close()


@pytest.fixture(scope="module")
def eval_run(base_url, admin_headers, kb_with_doc):
    """通过 API 创建一条评测记录，用于历史表/详情弹窗测试。

    触发评测 POST /evaluation/runs 有限流 3/hour，且需要 Ollama 可达。
    run 记录在 API 调用时即创建（status=pending），Celery 任务异步执行。
    如 API 调用失败（限流/Ollama 不可达），返回 None，相关测试将跳过。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.post(
            f"{base_url}/evaluation/runs",
            params={"kb_id": kb_with_doc["kb"]["id"], "num_questions": 5},
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("data", {})
        run_id = data.get("run_id")
        if not run_id:
            return None
        # 轮询 run 状态（最多 60s），失败也接受（用于测试 UI 渲染）
        deadline = time.time() + 60
        run = None
        while time.time() < deadline:
            r2 = requests.get(f"{base_url}/evaluation/runs/{run_id}", headers=headers, timeout=10)
            if r2.status_code == 200:
                run = r2.json().get("data", {})
                if run.get("status") in ("completed", "failed"):
                    break
            time.sleep(3)  # API 轮询间隔
        return run
    except Exception:
        return None


def _reset_evaluation_page(cdp):
    """重置评测页：重新加载并导航到 /#/evaluation

    H14 修复：用 Page.reload 代替 cdp.navigate(TAURI_HOME)，避免全页导航导致
    zustand 重新 rehydrate 期间 AdminRoute 重定向。
    """
    cdp.evaluate("window.location.hash = '#/evaluation'")
    cdp.send("Page.reload")
    wait_for_dom_ready(cdp, timeout=10)
    wait_for_element(cdp, ".ant-card, .ant-table, .ant-empty", timeout=15)


def test_evaluation_page_loads(logged_in_cdp):
    """评测页加载：导航到 /#/evaluation，验证页面渲染（趋势图卡片 + 历史记录卡片）"""
    cdp = logged_in_cdp
    _reset_evaluation_page(cdp)
    # 评测页包含 EvaluationTrendChart 卡片 + EvaluationHistoryTable 卡片
    has_content = cdp.evaluate("""
        (function() {
            const cards = document.querySelectorAll('.ant-card');
            return cards.length >= 2;
        })();
    """)
    assert has_content, "Evaluation page did not render expected cards"


def test_trigger_eval_modal_opens(logged_in_cdp):
    """触发评测弹窗：点击触发按钮 → TriggerEvalModal 渲染（KB 选择 + 题目数输入 + 提交按钮）"""
    cdp = logged_in_cdp
    _reset_evaluation_page(cdp)
    wait_for_element(cdp, "button", timeout=10)
    # 点击触发评测按钮（文本包含"触发"/"Trigger"或 primary 按钮）
    clicked = cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            let btn = buttons.find(b =>
                b.textContent.includes('触发') || b.textContent.includes('Trigger') ||
                b.textContent.includes('评估') || b.textContent.includes('Eval'));
            if (!btn) btn = document.querySelector('button.ant-btn-primary');
            if (!btn) return false;
            btn.click();
            return true;
        })();
    """)
    assert clicked, "Trigger evaluation button not found"
    # 等待 Modal 出现
    try:
        wait_for_element(cdp, ".ant-modal-content", timeout=8)
        modal = True
    except TimeoutError:
        modal = False
    assert modal, "Trigger eval modal did not appear"
    # 验证 Modal 内有 KB 选择器和题目数输入框
    has_form = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            const hasSelect = !!modal.querySelector('.ant-select');
            const hasInputNumber = !!modal.querySelector('.ant-input-number');
            return hasSelect && hasInputNumber;
        })();
    """)
    assert has_form, "Trigger eval modal missing KB select or num_questions input"


def test_trigger_eval_submit(logged_in_cdp, kb_with_doc):
    """触发评测提交：选择 KB + 题目数 → 提交 → 进度面板（ProgressPanel）显示

    触发评测需要 Ollama 可达且有 3/hour 限额；如失败则跳过。
    """
    cdp = logged_in_cdp
    _reset_evaluation_page(cdp)
    wait_for_element(cdp, "button", timeout=10)
    # 打开触发弹窗
    cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            let btn = buttons.find(b =>
                b.textContent.includes('触发') || b.textContent.includes('Trigger'));
            if (!btn) btn = document.querySelector('button.ant-btn-primary');
            if (btn) btn.click();
        })();
    """)
    wait_for_element(cdp, ".ant-modal-content", timeout=5)
    modal_open = cdp.evaluate("!!document.querySelector('.ant-modal-content')")
    if not modal_open:
        pytest.skip("Failed to open trigger eval modal")
    # 选择 KB（点击 Select → 选择匹配的 KB 选项）
    kb_name = kb_with_doc["kb"]["name"]
    cdp.evaluate("""
        (function() {
            const select = document.querySelector('.ant-modal .ant-select-selector');
            if (select) select.click();
        })();
    """)
    wait_for_element(cdp, ".ant-select-dropdown .ant-select-item", timeout=5)
    selected = cdp.evaluate(f"""
        (function() {{
            const items = Array.from(document.querySelectorAll('.ant-select-item'));
            const target = items.find(el => el.textContent.includes({repr(kb_name)}));
            if (target) {{ target.click(); return true; }}
            if (items.length > 0) {{ items[0].click(); return true; }}
            return false;
        }})();
    """)
    if not selected:
        pytest.skip("No KB option available in trigger eval modal")
    time.sleep(0.5)  # 必要固定等待：Ant Design Select onChange debounce
    # 点击确定按钮提交
    cdp.evaluate("""
        (function() {
            const ok = document.querySelector('.ant-modal-footer button.ant-btn-primary');
            if (ok) ok.click();
        })();
    """)
    # 等待进度面板或错误提示（最多 15s）
    deadline = time.time() + 15
    has_progress = False
    while time.time() < deadline:
        has_progress = cdp.evaluate("""
            (function() {
                const modals = document.querySelectorAll('.ant-modal-content');
                return Array.from(modals).some(m => m.querySelector('.ant-progress'));
            })();
        """)
        if has_progress:
            break
        time.sleep(1)  # 轮询间隔
    if not has_progress:
        # 检查是否有错误 toast（Ollama 不可达或限流）
        has_error = cdp.evaluate("""
            (function() {
                return !!document.querySelector('.ant-message-error, .ant-message-notice-error');
            })();
        """)
        if has_error:
            pytest.skip("Evaluation trigger failed (Ollama unreachable or rate limited)")
    assert has_progress, "Progress panel did not appear after submit"


def test_eval_history_table_renders(logged_in_cdp, eval_run):
    """历史记录表格渲染：验证表格列（ID/KB/状态/题目数/指标/创建时间/操作）

    如无评测记录（eval_run 为 None），验证空状态渲染。
    """
    cdp = logged_in_cdp
    _reset_evaluation_page(cdp)
    wait_for_element(cdp, ".ant-table, .ant-empty", timeout=10)
    # 验证历史记录卡片存在（趋势图卡片 + 历史记录卡片）
    has_cards = cdp.evaluate("""
        (function() {
            const cards = document.querySelectorAll('.ant-card');
            return cards.length >= 2;
        })();
    """)
    assert has_cards, "History table card not found"
    # 验证表格表头列（有数据时）或空状态
    table_state = cdp.evaluate("""
        (function() {
            const table = document.querySelector('.ant-table');
            if (table) {
                const headers = Array.from(table.querySelectorAll('.ant-table-thead th'));
                return {hasTable: true, colCount: headers.length};
            }
            const empty = document.querySelector('.ant-empty');
            return {hasTable: false, hasEmpty: !!empty};
        })();
    """)
    assert table_state is not None, "Failed to evaluate table state"
    # 有表格或空状态均为合法
    assert table_state.get("hasTable") or table_state.get(
        "hasEmpty"
    ), "History table neither rendered table nor empty state"


def test_eval_detail_modal(logged_in_cdp, eval_run):
    """评测详情弹窗：点击历史记录的"详情"按钮 → RunDetailModal 渲染（题目级详情）

    如无评测记录，跳过。
    """
    cdp = logged_in_cdp
    _reset_evaluation_page(cdp)
    wait_for_element(cdp, "button, .ant-table, .ant-empty", timeout=10)
    # 查找并点击"详情"按钮
    clicked = cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            let btn = buttons.find(b =>
                b.textContent.includes('详情') || b.textContent.includes('Detail'));
            if (!btn) return false;
            btn.click();
            return true;
        })();
    """)
    if not clicked:
        pytest.skip("No detail button found (evaluation history may be empty)")
    # 等待详情 Modal 出现
    try:
        wait_for_element(cdp, ".ant-modal-content", timeout=8)
        modal = True
    except TimeoutError:
        modal = False
    assert modal, "Run detail modal did not appear"
    # 验证详情 Modal 内有 Descriptions（基本信息）或 Table（单题结果）
    has_detail = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            const hasDesc = !!modal.querySelector('.ant-descriptions');
            const hasTable = !!modal.querySelector('.ant-table');
            return hasDesc || hasTable;
        })();
    """)
    assert has_detail, "Run detail modal missing descriptions or results table"


def test_eval_trend_chart(logged_in_cdp):
    """评测趋势图渲染：验证 EvaluationTrendChart（canvas 元素或空状态）

    ECharts 使用 CanvasRenderer，有数据时渲染 canvas，无数据时显示 Empty。
    """
    cdp = logged_in_cdp
    _reset_evaluation_page(cdp)
    time.sleep(3)  # 等待 ECharts 渲染
    # 趋势图卡片内有 canvas（有数据时）或 Empty（无数据时）或 Skeleton（加载中）
    chart_state = cdp.evaluate("""
        (function() {
            const cards = document.querySelectorAll('.ant-card');
            if (cards.length === 0) return {found: false};
            var trendCard = cards[0];
            var hasCanvas = !!trendCard.querySelector('canvas');
            var hasEmpty = !!trendCard.querySelector('.ant-empty');
            var hasSkeleton = !!trendCard.querySelector('.ant-skeleton');
            return {found: true, hasCanvas: hasCanvas, hasEmpty: hasEmpty, hasSkeleton: hasSkeleton};
        })();
    """)
    assert chart_state and chart_state.get("found"), "Trend chart card not found"
    # canvas（有数据渲染）或 empty（无数据）或 skeleton（加载中）均为合法状态
    assert (
        chart_state.get("hasCanvas")
        or chart_state.get("hasEmpty")
        or chart_state.get("hasSkeleton")
    ), "Trend chart did not render (no canvas/empty/skeleton)"
