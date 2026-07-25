"""Prompt builder with DB-backed version management.

Task 10: Prompt 模板版本化管理
- prompt_templates 表存储版本化的 prompt 模板
- 启动时加载到内存缓存，支持热加载
- DB 不可用时 fallback 到默认值，避免启动失败
"""

import threading

from loguru import logger
from sqlalchemy import select

from app.db.prompt_template import PromptTemplate

# 默认 SYSTEM_PROMPT（fallback 用，DB 不可用或无记录时使用）
DEFAULT_SYSTEM_PROMPT = """你是知识库问答助手。根据以下文档片段回答问题,并在引用处标注 [n](n 为文档序号)。
【回答要求】
1. 仅依据提供的文档片段回答,不要编造信息
2. 引用文档时在句末标注 [1]、[2] 等序号
3. 如果文档中没有相关信息,如实回答"根据现有文档,我无法回答这个问题"
4. 末尾不要列出参考来源,系统会自动生成。
5. 回答要简洁、准确、有条理
"""

# prompt 模板名称常量
SYSTEM_PROMPT_NAME = "system_prompt"
# 默认版本号（无 DB 记录时使用）
DEFAULT_PROMPT_VERSION = "default-v1"


class _PromptCache:
    """Prompt 模板内存缓存（线程安全）。

    启动时从 DB 加载 active 模板到内存；
    支持 reload() 热加载（运维更新 DB 后调用）；
    DB 不可用时 fallback 到默认值。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._content: str = DEFAULT_SYSTEM_PROMPT
        self._version: str = DEFAULT_PROMPT_VERSION
        self._loaded: bool = False

    @property
    def content(self) -> str:
        return self._content

    @property
    def version(self) -> str:
        return self._version

    async def load(self, db=None) -> None:
        """从 DB 加载 active prompt 模板。DB 不可用时保留默认值。

        db 参数为 None 时自行创建 async session。
        """
        try:
            if db is None:
                from app.database import async_session

                async with async_session() as session:
                    await self._load_from_db(session)
            else:
                await self._load_from_db(db)
        except Exception as e:
            logger.warning(f"Failed to load prompt templates from DB, using default: {e}")
            with self._lock:
                self._content = DEFAULT_SYSTEM_PROMPT
                self._version = DEFAULT_PROMPT_VERSION
                self._loaded = True

    async def _load_from_db(self, session) -> None:
        """从 DB 加载 active system_prompt 模板。"""
        result = await session.execute(
            select(PromptTemplate)
            .where(
                PromptTemplate.name == SYSTEM_PROMPT_NAME,
                PromptTemplate.is_active.is_(True),
            )
            .order_by(PromptTemplate.created_at.desc())
            .limit(1)
        )
        template = result.scalar_one_or_none()
        with self._lock:
            if template:
                self._content = template.content
                self._version = template.version
                logger.info(
                    f"Loaded prompt template '{SYSTEM_PROMPT_NAME}' version '{template.version}' from DB"
                )
            else:
                # DB 中无记录 → 使用默认值
                self._content = DEFAULT_SYSTEM_PROMPT
                self._version = DEFAULT_PROMPT_VERSION
                logger.info(
                    f"No active prompt template in DB, using default version '{DEFAULT_PROMPT_VERSION}'"
                )
            self._loaded = True

    def reload_sync(self, content: str, version: str) -> None:
        """同步设置缓存内容（用于测试或手动热加载）。"""
        with self._lock:
            self._content = content
            self._version = version

    @property
    def is_loaded(self) -> bool:
        return self._loaded


# 模块级单例缓存
_prompt_cache = _PromptCache()


def get_system_prompt() -> str:
    """获取当前 system prompt 内容（从内存缓存读取，DB 不可用时为默认值）。"""
    return _prompt_cache.content


def get_prompt_version() -> str:
    """获取当前 prompt 版本号（用于记录到 chat_messages.prompt_version）。"""
    return _prompt_cache.version


async def load_prompt_templates(db=None) -> None:
    """启动时或热加载时调用：从 DB 加载 prompt 模板到内存缓存。

    db 参数可选，传入则复用现有 session；不传则自建 session。
    失败时 fallback 到默认值，不抛异常。
    """
    await _prompt_cache.load(db)


def build_rag_prompt(query: str, chunks: list[dict]) -> str:
    """构造带引用标记的 RAG prompt"""
    parts = ["【文档片段】"]
    for i, chunk in enumerate(chunks, 1):
        filename = chunk.get("filename", "未知文档")
        page = chunk.get("page")
        page_info = f" 第{page}页" if page else ""
        content = chunk.get("content", "")
        parts.append(f"\n[{i}] 【{filename}】{page_info}")
        parts.append(f"内容:{content}")
    parts.append(f"\n\n【用户问题】\n{query}")
    return "\n".join(parts)


def build_context_messages(
    system_prompt: str,
    rag_context: str,
    history: list[dict],
    current_query: str,
    summary: str | None = None,
) -> list[dict]:
    """构造完整的 messages 列表"""
    messages = [{"role": "system", "content": system_prompt}]
    if summary:
        messages.append({"role": "system", "content": f"【对话历史摘要】\n{summary}"})
    messages.append({"role": "system", "content": rag_context})
    messages.extend(history)
    messages.append({"role": "user", "content": current_query})
    return messages


# 向后兼容：SYSTEM_PROMPT 作为模块级常量保留
# 优先从缓存读取，DB 不可用时为默认值
SYSTEM_PROMPT = get_system_prompt()
