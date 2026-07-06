# conftest.py - 全局测试 fixture
#
# 注意：不要再重新定义 event_loop fixture。
# pytest-asyncio 0.23+ 与 Python 3.12 下，自定义 event_loop 已弃用且会导致
# "There is no current event loop in thread 'MainThread'" 错误。
# asyncio_mode = auto（见 pyproject.toml）会自动管理事件循环。
