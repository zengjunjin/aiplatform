from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


class SessionCreate(BaseModel):
    kb_id: Optional[int] = None
    title: str = Field(default="新建会话", max_length=200)


class SessionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    kb_id: Optional[int] = None


class SessionOut(BaseModel):
    id: int
    user_id: int
    kb_id: Optional[int]
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    model: Optional[str] = None  # 用户指定的模型名称（Provider name），不传则自动选择


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    referenced_chunks: Optional[Any]
    token_input: Optional[int]
    token_output: Optional[int]
    latency_ms: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class Reference(BaseModel):
    chunk_id: int
    doc_id: int
    filename: str
    page: Optional[int]
    snippet: str
    score: float
