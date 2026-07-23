"""CDP (Chrome DevTools Protocol) 客户端

通过 http://localhost:9223/json 获取 WebView2 调试端点，
然后建立 WebSocket 连接，发送 CDP 命令。
"""
import json
import time
import base64
import requests
import websocket  # websocket-client
from typing import Optional


class CdpClient:
    def __init__(self, cdp_port: int = 9223, host: str = "localhost"):
        self.cdp_port = cdp_port
        self.host = host
        self.ws: Optional[websocket.WebSocket] = None
        self.msg_id = 0
        self.target_id: Optional[str] = None

    def connect(self, timeout: int = 10) -> None:
        """连接到 Tauri WebView2"""
        # 1. 获取调试目标列表
        r = requests.get(f"http://{self.host}:{self.cdp_port}/json",
                         timeout=timeout)
        r.raise_for_status()
        targets = r.json()
        page_target = next(
            (t for t in targets if t.get("type") == "page"), None
        )
        if not page_target:
            raise RuntimeError(f"No page target found in CDP: {targets}")
        self.target_id = page_target["id"]
        ws_url = page_target["webSocketDebuggerUrl"]

        # 2. 建立 WebSocket 连接
        # suppress_origin=True: 不发送 Origin 头，避免 Edge/Chromium 的
        # --remote-allow-origins 检查导致 403 Forbidden（新版 WebView2 安全限制）
        self.ws = websocket.create_connection(
            ws_url, timeout=timeout, suppress_origin=True
        )
        # 3. 启用必要的域
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Network.enable")

    def send(self, method: str, params: dict = None, timeout: int = 30) -> dict:
        """发送 CDP 命令并等待结果"""
        if not self.ws:
            raise RuntimeError("Not connected")
        self.msg_id += 1
        msg = {"id": self.msg_id, "method": method}
        if params:
            msg["params"] = params
        self.ws.send(json.dumps(msg))

        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == self.msg_id:
                if "error" in data:
                    raise RuntimeError(f"CDP error: {data['error']}")
                return data.get("result", {})
            # 其他事件忽略
        raise TimeoutError(f"Timeout waiting for CDP response: {method}")

    def navigate(self, url: str, wait_until: str = "load") -> None:
        """导航到 URL 并等待加载"""
        self.send("Page.navigate", {"url": url})
        # 简单等待
        time.sleep(1.5)

    def evaluate(self, expression: str, await_promise: bool = False):
        """执行 JavaScript 并返回结果"""
        params = {"expression": expression,
                  "returnByValue": True,
                  "awaitPromise": await_promise}
        result = self.send("Runtime.evaluate", params)
        value = result.get("result", {})
        if value.get("subtype") == "error":
            raise RuntimeError(f"JS error: {value.get('description')}")
        return value.get("value")

    def click(self, x: int, y: int) -> None:
        """在指定坐标点击"""
        self.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })
        self.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y,
            "button": "left", "clickCount": 1,
        })

    def type_text(self, text: str) -> None:
        """输入文本（逐字符）"""
        for ch in text:
            self.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "text": ch,
            })
            self.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "text": ch,
            })

    def query_selector(self, selector: str) -> str:
        """通过 CSS 选择器查找元素，返回 box model"""
        result = self.send("DOM.getDocument", {"depth": 0})
        root_node = result["root"]
        node_result = self.send("DOM.querySelector", {
            "nodeId": root_node["nodeId"],
            "selector": selector,
        })
        node_id = node_result.get("nodeId", 0)
        if not node_id:
            raise RuntimeError(f"Element not found: {selector}")
        # 获取 bounding box
        box = self.send("DOM.getBoxModel", {"nodeId": node_id})
        return box

    def click_element(self, selector: str) -> None:
        """通过 CSS 选择器点击元素"""
        box = self.query_selector(selector)
        quads = box["model"]["content"]
        # 中心点
        x = sum(quads[0::2]) / 4
        y = sum(quads[1::2]) / 4
        self.click(int(x), int(y))

    def fill_input(self, selector: str, value: str) -> None:
        """通过 JS 设置 input 值（比 type_text 可靠）"""
        err_msg = f"Element not found: {selector}"
        self.evaluate(f"""
            (function() {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) throw new Error({json.dumps(err_msg)});
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(el, {json.dumps(value)});
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }})();
        """)

    def screenshot(self, file_path: str) -> None:
        """截屏保存到文件"""
        result = self.send("Page.captureScreenshot", {"format": "png"})
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(result["data"]))

    def close(self) -> None:
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
