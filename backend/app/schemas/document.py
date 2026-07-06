from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class DocumentOut(BaseModel):
    id: int
    kb_id: int
    uploader_id: int
    filename: str
    file_type: str
    file_size: int
    file_hash: str
    status: str
    chunk_count: int
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentUpdate(BaseModel):
    title: Optional[str] = None


class DocumentProgress(BaseModel):
    status: str
    progress: int
    chunk_count: int
    error_message: Optional[str]