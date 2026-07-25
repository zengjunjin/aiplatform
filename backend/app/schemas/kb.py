from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KBCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=1000)


class KBUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=1000)


class CollaboratorAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(..., ge=1)
    permission: str = Field("read", pattern="^(read|write|admin)$")


class CollaboratorOut(BaseModel):
    user_id: int
    username: str
    permission: str


class KBOut(BaseModel):
    id: int
    name: str
    description: str | None
    owner_id: int
    doc_count: int
    chunk_count: int
    collaborators: list[dict] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
