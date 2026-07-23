"""Prompt template model for versioned prompt management.

Task 10: Prompt 模板版本化管理
- prompt_templates 表存储版本化的 prompt 模板
- 启动时加载到内存，支持热加载
- chat_messages 表记录使用的 prompt_version
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.db.base import Base


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
