from pydantic import BaseModel
from typing import Literal, Optional


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
    role: Literal["user", "admin"]


class UpdateStatusRequest(BaseModel):
    is_active: bool