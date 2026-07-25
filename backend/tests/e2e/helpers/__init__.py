"""E2E 测试辅助工具

统一导出常用符号，简化测试文件 import：
    from tests.e2e.helpers import make_cdp_client, login_cdp_session, wait_for_element
"""

from tests.e2e.helpers import config
from tests.e2e.helpers.cdp_auth import (
    create_user_via_api,
    login_cdp_session,
    logout_cdp_session,
    make_cdp_client,
    switch_cdp_user,
    verify_api_call,
)
from tests.e2e.helpers.waiters import (
    wait_for,
    wait_for_dom_ready,
    wait_for_element,
    wait_for_url_change,
)

__all__ = [
    # config
    "config",
    # cdp_auth
    "create_user_via_api",
    "login_cdp_session",
    "logout_cdp_session",
    "make_cdp_client",
    "switch_cdp_user",
    "verify_api_call",
    # waiters
    "wait_for",
    "wait_for_dom_ready",
    "wait_for_element",
    "wait_for_url_change",
]
