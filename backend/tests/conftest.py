"""Shared pytest fixtures for backend tests.

注意：不要再重新定义 event_loop fixture。
pytest-asyncio 0.23+ 与 Python 3.12 下，自定义 event_loop 已弃用且会导致
"There is no current event loop in thread 'MainThread'" 错误。
asyncio_mode = auto（见 pyproject.toml）会自动管理事件循环。
"""

# pyarrow 兼容性 patch：datasets 2.14.x 依赖 pa.PyExtensionType，
# 但 pyarrow 15+ 移除了该属性（改用 pa.ExtensionType）。
# 在 import datasets/ragas 之前 patch，避免 AttributeError 导致测试收集失败。
import contextlib

import pyarrow as _pa

if not hasattr(_pa, "PyExtensionType"):
    _pa.PyExtensionType = _pa.ExtensionType

# ragas 兼容性 patch：ragas 0.2.x 依赖 langchain_community.chat_models.vertexai.ChatVertexAI，
# 但新版 langchain_community 已移除该模块（迁移到 langchain-google-vertexai 独立包）。
# 注入 mock 模块避免 ImportError，使 ragas 能正常 import（测试环境不实际调用 VertexAI）。
import sys as _sys
from unittest.mock import MagicMock as _MagicMock

if "langchain_community.chat_models.vertexai" not in _sys.modules:
    _mock_vertexai = _MagicMock()
    _mock_vertexai.ChatVertexAI = _MagicMock
    _sys.modules["langchain_community.chat_models.vertexai"] = _mock_vertexai

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

# test_auth_full_flow.py 是独立脚本（模块顶层调用 requests + sys.exit），
# 不是 pytest 测试模块。若被 pytest 导入会导致收集阶段 ConnectionError，
# 因此显式排除其收集。
collect_ignore = ["test_auth_full_flow.py"]


def pytest_configure(config):
    """条件性启用 pytest-rerunfailures 的 --reruns 选项。

    仅当 pytest-rerunfailures 已安装时才设置 reruns=2, delay=3。
    避免未安装时 pytest 因 --reruns 未知参数报错。
    （pyproject.toml addopts 中不直接写 --reruns，由本函数条件注入。）
    """
    try:
        import pytest_rerunfailures  # noqa: F401
    except ImportError:
        return
    # 插件已安装，设置默认重试参数（如命令行未显式指定）
    if hasattr(config.option, "reruns") and not config.option.reruns:
        config.option.reruns = 2
    if hasattr(config.option, "reruns_delay") and not config.option.reruns_delay:
        config.option.reruns_delay = 3


@pytest.fixture
def mock_db():
    """Mock AsyncSession for database operations."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    # 让 execute 返回一个有 scalars().all() / fetchall() 的 mock
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.fetchall.return_value = []
    session.execute.return_value = result
    return session


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.setex = AsyncMock(return_value=True)
    redis.exists = AsyncMock(return_value=False)
    return redis


@pytest.fixture
def audit_db():
    """Mock AsyncSession for audit_service tests.

    audit_service.log_audit 通过独立 async_session 写入审计日志，
    此 fixture 模拟该 session。测试可覆盖 commit 的 side_effect
    来验证异常吞掉逻辑。
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


@pytest.fixture
def audit_cm(audit_db):
    """Mock async context manager for audit_service.async_session.

    用法:
        with patch("app.services.audit_service.async_session", return_value=audit_cm):
            await audit_service.log_audit(...)
        audit_db.add.assert_called_once()

    需要模拟异常时，在 patch 前覆盖:
        audit_cm.__aenter__.side_effect = RuntimeError(...)
    """
    cm = AsyncMock()
    cm.__aenter__.return_value = audit_db
    cm.__aexit__.return_value = None
    return cm


@pytest.fixture
def make_auth_db():
    """Factory fixture to create mock AsyncSession for auth_service tests.

    替代 test_auth_api.py 中的内联 _make_db 辅助函数。

    用法:
        db = make_auth_db(user=fake_user)  # execute 返回该 user
        db = make_auth_db(user=None)       # execute 返回 None
    """

    def _make(user=None):
        db = AsyncMock()
        scalar = user if user is not None else None
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: scalar))
        return db

    return _make


@pytest.fixture
def make_user():
    """Factory fixture to create test user mocks (MagicMock with spec=User).

    替代各测试文件中重复的 _make_user 辅助函数，统一字段默认值。
    返回 MagicMock(spec=User)，按需覆盖字段。
    """
    from app.db.user import User

    def _make_user(
        user_id: int = 1,
        username: str = "tester",
        email: str = "t@example.com",
        role: str = "user",
        is_active: bool = True,
        password_hash: str = "hash",
    ):
        u = MagicMock(spec=User)
        u.id = user_id
        u.username = username
        u.email = email
        u.role = role
        u.is_active = is_active
        u.password_hash = password_hash
        u.created_at = MagicMock()
        u.created_at.isoformat.return_value = "2026-01-01T00:00:00"
        return u

    return _make_user


@pytest.fixture
def make_db():
    """Factory fixture to create mock AsyncSession.

    替代 test_document_service.py 和 test_kb_permissions.py 中的 _make_db。
    支持两种模式：
    - KB 模式: make_db(kb=some_kb) → execute 返回 scalar_one_or_none=kb
    - Document 模式: make_db(doc_count=N, existing_doc=...) → 两次 execute
    """

    def _make_db(
        kb=None,
        doc_count=0,
        existing_doc=None,
        commit_side_effect=None,
    ):
        db = AsyncMock()
        if kb is not None:
            result = MagicMock()
            result.scalar_one_or_none.return_value = kb
            db.execute.return_value = result
        else:
            count_result = MagicMock()
            count_result.scalar_one.return_value = doc_count
            existing_result = MagicMock()
            existing_result.scalar_one_or_none.return_value = existing_doc
            db.execute = AsyncMock(side_effect=[count_result, existing_result])
            if commit_side_effect:
                db.commit = AsyncMock(side_effect=commit_side_effect)

            async def fake_refresh(obj, *args, **kwargs):
                obj.id = 99

            db.refresh = AsyncMock(side_effect=fake_refresh)
        return db

    return _make_db


@pytest.fixture
def auth_headers(make_user):
    """Request headers with a mocked JWT token."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def request_mock():
    """真实的 starlette Request，slowapi @limiter.limit 装饰器需要。

    提供 scope 字段以支持 _rate_limit_key 中的 request.client.host 和 headers 查询。
    """
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/test",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _reset_limiter_storage():
    """每个测试运行前清空 slowapi 内存存储的限流计数器。

    避免同一进程内多测试累积触发限流（60/minute 默认限制下，若不重置，
    第 61 次同 key 调用会失败）。autouse=True 自动应用于所有测试。
    """
    from app.core.middleware import limiter

    storage = limiter._storage
    # MemoryStorage.reset() 清空计数器和过期时间表
    reset = getattr(storage, "reset", None)
    if reset is not None:
        with contextlib.suppress(Exception):
            reset()
    yield


@pytest.fixture(autouse=True)
def _reset_model_factory_singletons():
    """每个测试前重置 ModelFactory 单例缓存。

    防止测试间状态泄漏：测试 A 创建了 OllamaLLMProvider 实例并缓存，
    测试 B 拿到的是 A 的实例而非新建。重置确保每个测试从干净的
    ModelFactory._llm/_embedding/_reranker = None 开始。

    test_models.py::TestModelFactory.setup_method 已自行重置，
    本 fixture 与之兼容（幂等操作）。
    """
    from app.models.factory import ModelFactory

    ModelFactory._llm = None
    ModelFactory._embedding = None
    ModelFactory._reranker = None
    yield
    # 测试结束后也重置，避免后续测试受影响
    ModelFactory._llm = None
    ModelFactory._embedding = None
    ModelFactory._reranker = None


@pytest.fixture(autouse=True)
def _mock_reranker_model_download():
    """全局 mock sentence_transformers.CrossEncoder，避免 CI 触发 HuggingFace 1.1GB 下载。

    LocalBgeRerankerProvider._load_model_sync 内部 `from sentence_transformers
    import CrossEncoder` 会触发 HuggingFace 下载 bge-reranker-base（~1.1GB），
    CI 环境下会超时或失败。通过 sys.modules 注入 mock 模块，让 import 拿到
    MagicMock 而非真实 CrossEncoder。

    test_models.py::TestLocalBgeRerankerProvider 的测试用 patch.dict(sys.modules)
    显式替换 sentence_transformers，会覆盖本 fixture 的注入，因此不受影响。
    """
    fake_module = _MagicMock()
    fake_module.CrossEncoder = _MagicMock(return_value=_MagicMock())

    original = _sys.modules.get("sentence_transformers")
    _sys.modules["sentence_transformers"] = fake_module
    try:
        yield
    finally:
        if original is not None:
            _sys.modules["sentence_transformers"] = original
        else:
            _sys.modules.pop("sentence_transformers", None)


@pytest.fixture
def mock_sse_common():
    """Mock SSE 流式响应的公共依赖（不随测试变化的 patch）。

    抽取 test_chat_api.py 中 12+ 处重复的 patch，减少测试代码冗余。
    测试仍需自行 patch get_session/retrieve/rerank/build_messages/ModelRouter.select
    （这些依赖测试特定数据）。
    如需覆盖某个公共 patch（如 is_cancelled=True），在测试内用 with patch(...) 覆盖。
    """
    from unittest.mock import patch

    patches = [
        patch(
            "app.services.chat_service.save_message", new=AsyncMock(return_value=MagicMock(id=99))
        ),
        patch("app.services.chat_service.append_to_context", new=AsyncMock()),
        patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
        patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=False)),
        patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
        patch("app.rag.reference_parser.parse_references", return_value=[]),
        patch("app.utils.token_counter.count_tokens", return_value=5),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()
