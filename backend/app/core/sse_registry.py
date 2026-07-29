"""活跃 SSE 请求注册表：切断 api/v1/chat.py → main.py 反向循环依赖（架构评审 P0-3）。

原设计：main.py 顶部定义 `_active_sse_requests: set[asyncio.Task]`，
chat._run_sse_stream 通过函数级 `from app.main import _active_sse_requests` 注册/移除。

问题：
- chat.py 通过反向 import main 形成 main → chat_service → ... → chat.py → main 的循环依赖，
  必须用延迟 import 才能工作，违反架构分层契约（api 不能反向依赖入口层 main）。
- 引入 sse_registry.py 后，chat.py → sse_registry ← main.py，依赖方向单层合法：
  main.py 从 sse_registry 导入 `all()` 做优雅关闭，
  chat.py 从 sse_registry 导入 `register/discard` 做生命周期管理。
"""
from __future__ import annotations

import asyncio
from typing import Set

_active_sse_requests: Set[asyncio.Task] = set()


def register(task: asyncio.Task) -> None:
    """注册活跃 SSE Task，供 shutdown 等待其完成。"""
    _active_sse_requests.add(task)


def discard(task: asyncio.Task) -> None:
    """移除已完成 SSE Task；Task 不存在时不抛错。"""
    _active_sse_requests.discard(task)


def all() -> Set[asyncio.Task]:
    """返回当前全部活跃 SSE Task 的引用副本（防止 shutdown 迭代期间并发修改）。"""
    return set(_active_sse_requests)
