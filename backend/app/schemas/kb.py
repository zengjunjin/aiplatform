from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class KBCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)


class KBUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)


class CollaboratorAdd(BaseModel):
    user_id: int
    permission: str = Field("read", pattern="^(read|write|admin)$")


class CollaboratorOut(BaseModel):
    user_id: int
    username: str
    permission: str


class KBOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    owner_id: int
    doc_count: int
    chunk_count: int
    collaborators: Optional[List[dict]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True