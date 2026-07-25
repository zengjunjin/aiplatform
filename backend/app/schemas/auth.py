from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=3, max_length=254, description="用户名或邮箱")
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    old_password: str
    new_password: str = Field(..., min_length=8, max_length=100)
    confirm_password: str

    @model_validator(mode="after")
    def check_passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("两次输入的新密码不一致")
        return self


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class LoginUserInfo(BaseModel):
    """登录返回的用户精简信息（不含 is_active 等敏感字段）。"""

    id: int
    username: str
    email: str
    role: str


class LoginResponse(TokenResponse):
    """登录/刷新 token 的完整响应（含用户信息）。"""

    user: LoginUserInfo
