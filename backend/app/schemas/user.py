from typing import Literal

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role: Literal["user", "admin"]
    is_active: bool

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    id: int
    username: str
    email: str
    role: Literal["user", "admin"]
    is_active: bool

    class Config:
        from_attributes = True


class UpdateRoleRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    role: Literal["user", "admin"]


class UpdateStatusRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    is_active: bool
