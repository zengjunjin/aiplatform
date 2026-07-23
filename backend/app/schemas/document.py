from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str | None = None


class DocumentProgress(BaseModel):
    status: str
    progress: int
    chunk_count: int
    error_message: str | None
