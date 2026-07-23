"""轮询/等待工具"""
import time
from typing import Callable, Any


def wait_for(predicate: Callable[[], Any], timeout: int = 30,
             interval: float = 0.5, message: str = "") -> Any:
    """等待条件成立"""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as e:
            last_err = e
        time.sleep(interval)
    msg = f"Timeout after {timeout}s: {message}"
    if last_err:
        msg += f" (last error: {last_err})"
    raise TimeoutError(msg)


def wait_for_dom_ready(cdp, timeout: int = 10) -> None:
    """等待 DOM ready"""
    wait_for(
        lambda: cdp.evaluate("document.readyState") == "complete",
        timeout=timeout,
        message="DOM ready",
    )


def wait_for_element(cdp, selector: str, timeout: int = 10) -> bool:
    """等待元素出现"""
    return wait_for(
        lambda: cdp.evaluate(f"!!document.querySelector({repr(selector)})"),
        timeout=timeout,
        message=f"Element {selector} not found",
    )


def wait_for_url_change(cdp, expected_part: str, timeout: int = 10) -> None:
    """等待 URL 变化"""
    wait_for(
        lambda: expected_part in cdp.evaluate("window.location.href"),
        timeout=timeout,
        message=f"URL did not change to contain {expected_part}",
    )
