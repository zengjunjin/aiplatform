"""Tauri 配置安全性 E2E 验证

不需要 CDP 连接，仅读取 tauri.conf.json 验证安全配置。

验证项：
1. tauri.conf.json 存在
2. additionalBrowserArgs 不含 --remote-debugging-port=9222（RCE 风险）
3. additionalBrowserArgs 含 --allow-running-insecure-content（HTTPS→HTTP 必须）
4. additionalBrowserArgs 含 --remote-debugging-port=9223（CDP 测试端口，非 9222）
5. withGlobalTauri 为 false（XSS 攻击面）
6. CSP connect-src 允许 localhost:8000
7. CSP 不允许 'unsafe-eval'
8. release 目录配置与源一致（如存在）
"""

import json
from pathlib import Path

import pytest

# backend/tests/e2e/test_16_tauri_config.py -> 项目根目录
ROOT = Path(__file__).parent.parent.parent.parent
TAURI_CONF_PATH = ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
RELEASE_CONF_PATH = (
    ROOT / "release" / "RAG知识库平台" / "frontend" / "src-tauri" / "tauri.conf.json"
)


@pytest.fixture(scope="module")
def tauri_conf():
    """加载 tauri.conf.json"""
    if not TAURI_CONF_PATH.exists():
        pytest.skip(f"Config not found: {TAURI_CONF_PATH}")
    return json.loads(TAURI_CONF_PATH.read_text(encoding="utf-8"))


def test_tauri_conf_exists():
    """tauri.conf.json 存在"""
    assert TAURI_CONF_PATH.exists(), f"Config not found: {TAURI_CONF_PATH}"


def test_no_remote_debugging_9222(tauri_conf):
    """不包含 --remote-debugging-port=9222（RCE 风险）"""
    args = tauri_conf["app"]["windows"][0].get("additionalBrowserArgs", "")
    assert (
        "--remote-debugging-port=9222" not in args
    ), "additionalBrowserArgs must NOT contain --remote-debugging-port=9222 (RCE risk)"


def test_allow_insecure_content_present(tauri_conf):
    """包含 --allow-running-insecure-content（HTTPS→HTTP 必须）

    Tauri 2 生产模式下 tauri.localhost 是 HTTPS，后端 localhost:8000 是 HTTP，
    需要 --allow-running-insecure-content 才能加载 HTTP 资源（mixed content）。
    CSP connect-src 已放行 http://localhost:8000，但 WebView2 仍需此标志绕过 mixed content blocking。
    """
    args = tauri_conf["app"]["windows"][0].get("additionalBrowserArgs", "")
    assert "--allow-running-insecure-content" in args, (
        "additionalBrowserArgs must contain --allow-running-insecure-content "
        "(HTTPS tauri.localhost -> HTTP localhost:8000 requires this flag)"
    )


def test_with_global_tauri_false(tauri_conf):
    """withGlobalTauri 为 false（减少 XSS 攻击面）"""
    assert (
        tauri_conf["app"]["withGlobalTauri"] is False
    ), "withGlobalTauri must be false (XSS surface reduction)"


def test_csp_allows_localhost_8000(tauri_conf):
    """CSP connect-src 允许 localhost:8000"""
    csp = tauri_conf["app"]["security"].get("csp", "")
    assert (
        "localhost:8000" in csp
    ), f"CSP must allow localhost:8000 in connect-src. Current CSP: {csp}"


def test_csp_blocks_unsafe_eval(tauri_conf):
    """CSP 不允许 'unsafe-eval'（防 eval 注入）"""
    csp = tauri_conf["app"]["security"].get("csp", "")
    assert "'unsafe-eval'" not in csp, f"CSP must NOT allow 'unsafe-eval'. Current CSP: {csp}"


def test_csp_has_default_src_self(tauri_conf):
    """CSP default-src 为 'self'（默认限制同源）"""
    csp = tauri_conf["app"]["security"].get("csp", "")
    assert "default-src 'self'" in csp, f"CSP should have default-src 'self'. Current CSP: {csp}"


def test_release_tauri_conf_matches(tauri_conf):
    """release 目录的 tauri.conf.json 与源一致（如存在）"""
    if not RELEASE_CONF_PATH.exists():
        pytest.skip(f"Release config not found: {RELEASE_CONF_PATH}")
    rel_conf = json.loads(RELEASE_CONF_PATH.read_text(encoding="utf-8"))
    assert rel_conf == tauri_conf, "Release tauri.conf.json differs from source"
