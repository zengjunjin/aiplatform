from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    kb_id: int | None = None
    title: str = Field(default="新建会话", max_length=200)


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str | None = Field(default=None, max_length=200)
    kb_id: int | None = None


class SessionOut(BaseModel):
    id: int
    user_id: int
    kb_id: int | None
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    content: str = Field(..., min_length=1, max_length=5000)
    model: str | None = None  # 用户指定的模型名称（Provider name），不传则自动选择


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    referenced_chunks: Any | None
    token_input: int | None
    token_output: int | None
    latency_ms: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class Reference(BaseModel):
    chunk_id: int
    doc_id: int
    filename: str
    page: int | None
    snippet: str
    score: float
