# RAG 知识库平台 — 开发者指南

> 版本：v0.2.0
> 更新日期：2026-07-11

---

## 目录

1. [本地开发环境搭建](#1-本地开发环境搭建)
2. [项目结构说明](#2-项目结构说明)
3. [编码规范](#3-编码规范)
4. [测试指南](#4-测试指南)
5. [如何添加新的 LLM Provider](#5-如何添加新的-llm-provider)
6. [如何添加新的文档解析器](#6-如何添加新的文档解析器)

---

## 1. 本地开发环境搭建

### 1.1 前置要求

| 工具 | 最低版本 | 说明 |
|------|----------|------|
| Python | 3.12+ | 后端运行时 |
| Poetry | 1.8+ | Python 依赖管理 |
| Node.js | 20+ | 前端构建 |
| PostgreSQL | 15+ | 关系型数据库 |
| Redis | 7+ | 缓存与消息队列 |
| Qdrant | 1.10+ | 向量数据库 |
| Ollama | latest | 本地 LLM 推理（可选） |

### 1.2 后端开发环境

```bash
# 1. 进入后端目录
cd backend

# 2. 安装依赖
poetry install

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，设置 DEBUG=true 以启用 /docs 和 /redoc

# 4. 启动基础设施（Docker Compose）
cd ../deploy
docker compose up -d postgres redis qdrant ollama

# 5. 运行数据库迁移
cd ../backend
poetry run alembic upgrade head

# 6. 初始化管理员账号
poetry run python init_db.py

# 7. 启动开发服务器
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 8. 启动 Celery Worker（另一个终端）
poetry run celery -A app.tasks.celery_app worker --loglevel=info --concurrency=1
```

### 1.3 前端开发环境

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev
# 默认访问 http://localhost:5173

# 4. 代码检查
npm run lint

# 5. 格式化代码
npm run format
```

### 1.4 快速启动（仅后端 API 开发）

如果只需要开发后端 API（不需要前端），可以使用 Docker 快速启动：

```bash
# 启动全部基础设施 + 后端
docker compose -f deploy/docker-compose.yml up -d postgres redis qdrant

# 本地启动后端开发服务器
cd backend
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000/docs` 查看 Swagger API 文档。

### 1.5 拉取 Ollama 模型

```bash
# 拉取 LLM 模型
ollama pull qwen2.5:7b

# 拉取 Embedding 模型
ollama pull nomic-embed-text

# 验证模型已安装
ollama list
```

---

## 2. 项目结构说明

```
aiplatform/
├── backend/                         # 后端 Python 项目
│   ├── alembic/                     # 数据库迁移
│   │   ├── versions/                # 迁移版本文件
│   │   └── env.py                   # Alembic 配置
│   ├── app/                         # 应用主代码
│   │   ├── api/                     # API 路由层
│   │   │   ├── v1/                  # v1 API 端点
│   │   │   │   ├── auth.py          # 认证端点
│   │   │   │   ├── chat.py          # 对话端点
│   │   │   │   ├── documents.py     # 文档端点
│   │   │   │   ├── evaluation.py    # 评估端点
│   │   │   │   ├── knowledge_bases.py # 知识库端点
│   │   │   │   ├── router.py        # v1 路由聚合
│   │   │   │   ├── system.py        # 系统端点
│   │   │   │   └── users.py         # 用户管理端点
│   │   │   ├── v2/                  # v2 API 端点（规划中）
│   │   │   │   ├── __init__.py
│   │   │   │   └── router.py
│   │   │   └── deps.py              # 依赖注入（认证、权限）
│   │   ├── core/                    # 核心模块
│   │   │   ├── cache.py             # 缓存管理
│   │   │   ├── errors.py            # 错误码定义
│   │   │   ├── evaluation.py        # RAGAS 评估引擎
│   │   │   ├── exceptions.py        # 全局异常处理
│   │   │   ├── generation_manager.py # 生成管理
│   │   │   ├── metrics.py           # Prometheus 指标
│   │   │   ├── middleware.py         # 中间件（限流、日志、指标）
│   │   │   ├── model_health.py      # 模型健康检查
│   │   │   ├── model_router.py      # 模型智能路由
│   │   │   ├── prompt_optimizer.py  # Prompt 优化
│   │   │   └── security.py          # 安全工具
│   │   ├── db/                      # 数据库模型 (SQLAlchemy ORM)
│   │   │   ├── base.py              # 基类
│   │   │   ├── user.py
│   │   │   ├── knowledge_base.py
│   │   │   ├── document.py
│   │   │   ├── document_chunk.py
│   │   │   ├── chat_session.py
│   │   │   ├── chat_message.py
│   │   │   ├── evaluation.py
│   │   │   ├── feedback.py
│   │   │   ├── audit_log.py
│   │   │   └── sync_session.py
│   │   ├── models/                  # LLM/Embedding/Reranker 模型
│   │   │   ├── base.py              # 抽象基类
│   │   │   ├── factory.py           # ModelRegistry + ModelFactory
│   │   │   ├── ollama_provider.py   # Ollama Provider
│   │   │   ├── openai_compatible_provider.py # OpenAI 兼容 Provider
│   │   │   ├── cached_embedding.py  # 带缓存的 Embedding
│   │   │   └── reranker_provider.py # Reranker Provider
│   │   ├── parsers/                 # 文档解析器
│   │   │   ├── base.py              # 解析器抽象基类
│   │   │   ├── pdf_parser.py        # PDF 解析
│   │   │   ├── docx_parser.py       # DOCX 解析
│   │   │   ├── markdown_parser.py   # Markdown 解析
│   │   │   ├── text_parser.py       # 纯文本解析
│   │   │   └── chunker.py           # 文本分块器
│   │   ├── rag/                     # RAG 引擎
│   │   │   ├── retriever.py         # 混合检索器
│   │   │   ├── bm25.py              # BM25 检索
│   │   │   ├── reranker.py          # 重排序
│   │   │   ├── context_manager.py   # 上下文管理
│   │   │   ├── prompt_builder.py    # Prompt 构建
│   │   │   └── reference_parser.py  # 引用解析
│   │   ├── schemas/                 # Pydantic 请求/响应模型
│   │   │   ├── common.py            # 通用响应格式
│   │   │   ├── auth.py
│   │   │   ├── chat.py
│   │   │   ├── document.py
│   │   │   ├── feedback.py
│   │   │   ├── kb.py
│   │   │   └── user.py
│   │   ├── services/                # 业务逻辑层
│   │   │   ├── auth_service.py      # 认证服务
│   │   │   ├── chat_service.py      # 对话服务
│   │   │   ├── document_service.py  # 文档服务
│   │   │   ├── evaluation_service.py # 评估服务
│   │   │   ├── feedback_service.py  # 反馈服务
│   │   │   ├── kb_service.py        # 知识库服务
│   │   │   ├── user_service.py      # 用户服务
│   │   │   └── audit_service.py     # 审计服务
│   │   ├── tasks/                   # Celery 异步任务
│   │   │   ├── celery_app.py        # Celery 应用配置
│   │   │   ├── document_task.py     # 文档解析任务
│   │   │   ├── evaluation_task.py   # 评估任务
│   │   │   ├── feedback_analysis_task.py # 反馈分析任务
│   │   │   └── metrics_collector.py # 指标采集
│   │   ├── utils/                   # 工具函数
│   │   │   ├── storage.py           # 文件存储
│   │   │   └── token_counter.py     # Token 计数
│   │   ├── config.py                # 应用配置 (Pydantic Settings)
│   │   ├── database.py              # 数据库连接
│   │   ├── main.py                  # FastAPI 应用入口
│   │   └── redis_client.py          # Redis 客户端
│   ├── tests/                       # 测试
│   │   ├── integration/             # 集成测试
│   │   ├── performance/             # 性能测试
│   │   └── test_*.py                # 单元测试
│   ├── .env.example                 # 环境变量模板
│   ├── pyproject.toml               # Poetry 依赖配置
│   └── Dockerfile                   # Docker 构建文件
│
├── frontend/                        # 前端 React 项目
│   ├── src/
│   │   ├── api/                     # API 客户端
│   │   ├── components/              # UI 组件
│   │   ├── pages/                   # 页面组件
│   │   ├── store/                   # Zustand 状态管理
│   │   ├── types/                   # TypeScript 类型
│   │   ├── utils/                   # 工具函数
│   │   └── i18n/                    # 国际化
│   ├── package.json
│   └── vite.config.ts
│
├── deploy/                          # 部署配置
│   ├── docker-compose.yml           # Docker Compose 编排
│   ├── nginx.conf                   # Nginx 反向代理配置
│   ├── .env.example                 # 部署环境变量模板
│   └── Makefile                     # 部署快捷命令
│
├── docs/                            # 文档
│   ├── adr/                         # 架构决策记录
│   ├── superpowers/                 # 设计文档与计划
│   ├── api_guide.md                 # API 使用指南
│   ├── benchmark_report.md          # 性能基准报告
│   ├── deployment.md                # 部署文档
│   └── development.md               # 开发者指南（本文件）
│
├── CHANGELOG.md                     # 变更日志
├── Makefile                         # 项目级快捷命令
└── README.md                        # 项目说明
```

---

## 3. 编码规范

### 3.1 Python 后端

#### 代码风格
- 遵循 [PEP 8](https://peps.python.org/pep-0008/)
- 使用 `ruff` 或 `flake8` 进行代码检查
- 行宽限制：120 字符
- 使用类型注解（Type Hints）标注所有函数签名

#### 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块/文件 | snake_case | `chat_service.py` |
| 类 | PascalCase | `ChatService` |
| 函数/方法 | snake_case | `create_session()` |
| 变量 | snake_case | `user_id` |
| 常量 | UPPER_SNAKE_CASE | `MAX_FILE_SIZE_MB` |
| 私有方法 | _leading_underscore | `_validate_token()` |

#### 项目约定

```python
# 1. 统一响应格式：所有 API 端点使用 ok() / paginated_ok() 包装
from app.schemas.common import ok, paginated_ok

@router.get("/items")
async def list_items(...):
    items, total = await service.list_items(...)
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)

# 2. 异常处理：使用 AppException 及其子类
from app.core.exceptions import AppException, NotFoundError, ValidationError
from app.core.errors import ErrorCode

raise NotFoundError("Knowledge base not found")
raise AppException(code=ErrorCode.INTERNAL_ERROR, message="...", status_code=500)

# 3. 日志：使用 loguru
from loguru import logger
logger.info(f"User {user_id} created knowledge base {kb_id}")
logger.error(f"Failed to parse document {doc_id}: {e}")

# 4. 数据库操作：使用异步 SQLAlchemy
from sqlalchemy import select
from app.database import get_db

async def get_user(user_id: int, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
```

### 3.2 TypeScript 前端

#### 代码风格
- 使用 ESLint + Prettier 统一代码风格
- 运行 `npm run lint` 检查代码
- 运行 `npm run format` 格式化代码

#### 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 组件 | PascalCase | `ChatInput.tsx` |
| Hook | camelCase + use 前缀 | `useAuth.ts` |
| Store | camelCase + Store 后缀 | `authStore.ts` |
| 工具函数 | camelCase | `formatDate.ts` |
| 类型 | PascalCase | `ChatMessage` |

#### 项目约定
- 使用 Zustand 进行状态管理，按模块拆分 store
- API 调用统一通过 `src/api/` 下的模块
- 使用 `react-markdown` + `rehype-sanitize` 渲染 Markdown
- 所有用户可见文本使用 i18n 国际化

---

## 4. 测试指南

### 4.1 测试层级

| 层级 | 目录 | 命令 | 说明 |
|------|------|------|------|
| 单元测试 | `tests/test_*.py` | `pytest tests/` | 测试独立模块 |
| 集成测试 | `tests/integration/` | `pytest tests/integration/` | 需要真实数据库 |
| 性能测试 | `tests/performance/` | 见下方 | 基准测试脚本 |

### 4.2 运行测试

```bash
cd backend

# 运行所有单元测试
poetry run pytest tests/ -v --ignore=tests/integration --ignore=tests/performance

# 运行特定测试文件
poetry run pytest tests/test_retriever.py -v

# 运行特定测试用例
poetry run pytest tests/test_retriever.py::test_hybrid_retrieval -v

# 运行集成测试（需要基础设施）
poetry run pytest tests/integration/ -v -m "integration"

# 运行测试并生成覆盖率报告
poetry run pytest tests/ --cov=app --cov-report=html --cov-report=term \
  --ignore=tests/integration --ignore=tests/performance

# 运行性能基准测试
poetry run python tests/performance/benchmark_retrieval.py --kb-id 1
poetry run python tests/performance/benchmark_e2e.py --kb-id 1
```

### 4.3 测试标记

```python
# 使用 pytest 标记分类测试
@pytest.mark.integration   # 集成测试
@pytest.mark.real_rag      # 需要真实 RAG 管线的测试
@pytest.mark.e2e           # 端到端测试
@pytest.mark.slow          # 慢速测试
```

### 4.4 编写测试

```python
import pytest
from app.services import kb_service

@pytest.mark.asyncio
async def test_create_kb(db_session, test_user):
    """测试创建知识库"""
    from app.schemas.kb import KBCreate

    req = KBCreate(name="Test KB", description="A test knowledge base")
    kb = await kb_service.create_kb(req, test_user.id, db_session)

    assert kb.name == "Test KB"
    assert kb.user_id == test_user.id
    assert kb.doc_count == 0
```

---

## 5. 如何添加新的 LLM Provider

### 5.1 实现 Provider 类

创建 `backend/app/models/my_provider.py`：

```python
"""My Custom LLM Provider."""
from typing import AsyncIterator
from app.models.base import BaseLLMProvider


class MyCustomProvider(BaseLLMProvider):
    """对接自定义 LLM API 的 Provider。"""

    def __init__(
        self,
        model: str = "my-model",
        api_base: str = "https://api.example.com/v1",
        api_key: str = "",
        provider_name: str = "my-custom",
        max_retries: int = 3,
        timeout: float = 300.0,
    ):
        self._model = model
        self._api_base = api_base
        self._api_key = api_key
        self._provider_name = provider_name
        self._max_retries = max_retries
        self._timeout = timeout
        self._is_healthy = True

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_healthy(self) -> bool:
        return self._is_healthy

    async def check_health(self) -> bool:
        """健康检查：尝试调用 API 的 models 列表端点。"""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._api_base}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                self._is_healthy = resp.status_code == 200
                return self._is_healthy
        except Exception:
            self._is_healthy = False
            return False

    async def chat(self, messages: list[dict]) -> str:
        """非流式聊天。"""
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式聊天，逐 token 返回。"""
        import httpx

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        import json
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
```

### 5.2 注册 Provider

在 `backend/app/models/factory.py` 的 `ModelRegistry.init_from_config()` 中添加：

```python
if provider_type == "my_custom":
    provider = MyCustomProvider(
        api_base=api_base,
        api_key=api_key,
        model=model,
        provider_name=name,
        max_retries=max_retries,
        timeout=float(timeout),
    )
    cls.register(provider)
```

### 5.3 配置环境变量

在 `.env` 的 `LLM_PROVIDERS` JSON 中添加：

```json
{
  "name": "my-custom",
  "type": "my_custom",
  "api_base": "https://api.example.com/v1",
  "api_key": "sk-xxxxxxxxxxxxxxxxxxxx",
  "model": "my-model",
  "priority": 60,
  "max_retries": 3,
  "timeout": 120,
  "fallback_to": "ollama",
  "is_free": false
}
```

### 5.4 验证

```bash
# 重启后端
# 检查模型列表
curl http://localhost:8000/api/v1/system/models

# 测试对话
curl -N -X POST http://localhost:8000/api/v1/chat/sessions/1/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"Hello", "model":"my-custom"}'
```

---

## 6. 如何添加新的文档解析器

### 6.1 实现解析器类

创建 `backend/app/parsers/html_parser.py`：

```python
"""HTML 文档解析器。"""
from app.parsers.base import BaseParser


class HtmlParser(BaseParser):
    """解析 HTML 文件，提取纯文本内容。"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".html", ".htm"]

    def parse(self, file_path: str) -> str:
        """解析 HTML 文件，返回纯文本。

        Args:
            file_path: HTML 文件路径

        Returns:
            提取的纯文本内容
        """
        from bs4 import BeautifulSoup

        with open(file_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        soup = BeautifulSoup(html_content, "html.parser")

        # 移除 script 和 style 标签
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # 提取文本
        text = soup.get_text(separator="\n", strip=True)

        # 清理多余空白
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)
```

### 6.2 注册解析器

在 `backend/app/parsers/__init__.py` 中注册：

```python
from app.parsers.pdf_parser import PdfParser
from app.parsers.docx_parser import DocxParser
from app.parsers.markdown_parser import MarkdownParser
from app.parsers.text_parser import TextParser
from app.parsers.html_parser import HtmlParser  # 新增

PARSER_REGISTRY = {
    ".pdf": PdfParser(),
    ".docx": DocxParser(),
    ".md": MarkdownParser(),
    ".markdown": MarkdownParser(),
    ".txt": TextParser(),
    ".html": HtmlParser(),   # 新增
    ".htm": HtmlParser(),    # 新增
}
```

### 6.3 添加文件类型白名单

在 `backend/app/utils/storage.py` 中添加：

```python
ALLOWED_EXT = {
    ".pdf", ".docx", ".md", ".markdown", ".txt",
    ".html", ".htm",  # 新增
}
```

### 6.4 添加依赖（如需要）

```bash
cd backend
poetry add beautifulsoup4
```

### 6.5 编写测试

创建 `backend/tests/test_html_parser.py`：

```python
import pytest
from app.parsers.html_parser import HtmlParser


def test_html_parser_extracts_text(tmp_path):
    parser = HtmlParser()

    html_file = tmp_path / "test.html"
    html_file.write_text("""
    <html>
      <head><title>Test</title></head>
      <body>
        <h1>Hello World</h1>
        <p>This is a <b>test</b> paragraph.</p>
        <script>console.log('ignore me');</script>
      </body>
    </html>
    """, encoding="utf-8")

    result = parser.parse(str(html_file))

    assert "Hello World" in result
    assert "test paragraph" in result
    assert "console.log" not in result  # script 被移除
```

### 6.6 验证

```bash
# 运行新解析器的测试
poetry run pytest tests/test_html_parser.py -v

# 上传 HTML 文件测试
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.html" \
  -F "kb_id=1"
```