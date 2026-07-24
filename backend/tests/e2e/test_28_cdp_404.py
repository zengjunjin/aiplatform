"""CDP UI 测试 - 404 页与路由

需要 Tauri 以 CDP 端口 9223 启动。

测试场景：
1. 404 页渲染（404 文本 + 返回首页按钮）
2. 返回首页按钮跳转（跳转到 /#/dashboard 或 /#/login）

使用未登录 cdp fixture（404 页无需鉴权）。
"""
import os
import time

import pytest

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for_element

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def cdp():
    """未登录 CDP 客户端（404 页无需鉴权）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    yield client
    client.close()


def test_404_page_renders(cdp):
    """404 页渲染：导航到 /#/nonexistent，验证 404 文本与返回首页按钮

    NotFoundPage.tsx 使用 Ant Design Result，status="404"，title="404"，
    含"返回首页"按钮（navigate('/')）。
    """
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate("window.location.hash = '#/nonexistent'")
    time.sleep(2.5)
    # 验证 404 文本存在（Ant Design Result 渲染 404 状态）
    has_404 = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('*'))
                .some(el => el.textContent && el.textContent.includes('404'));
        })();
    """)
    assert has_404, "404 text not found on not-found page"
    # 验证返回首页按钮存在
    has_button = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('button'))
                .some(b => b.textContent.includes('返回首页'));
        })();
    """)
    assert has_button, "返回首页 button not found on 404 page"


def test_404_return_home(cdp):
    """返回首页按钮：点击后跳转到 /#/dashboard 或 /#/login

    NotFoundPage.tsx 的按钮 onClick 调用 navigate('/')。
    未登录时跳转到 /#/login，已登录时跳转到 /#/dashboard。
    本测试使用未登录 cdp，预期跳转到 /#/login。
    """
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate("window.location.hash = '#/nonexistent'")
    time.sleep(2.5)
    # 点击返回首页按钮
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('返回首页'));
            if (btn) btn.click();
        })();
    """)
    # 等待跳转（最长 10s）
    deadline = time.time() + 10
    while time.time() < deadline:
        url = cdp.evaluate("window.location.href")
        if url and ("/dashboard" in url or "/login" in url):
            return
        time.sleep(0.5)
    url = cdp.evaluate("window.location.href")
    assert "/dashboard" in url or "/login" in url, \
        f"Did not navigate to dashboard or login after clicking 返回首页: {url}"
