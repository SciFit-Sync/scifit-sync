import re
from datetime import date

from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    username: str
    password: str
    name: str
    email: EmailStr
    gender: str | None = None
    birth_date: date | None = None
    height: float | None = None
    weight: float | None = None
    career_level: str | None = None
    goals: list[str] = []

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if len(v) < 2 or len(v) > 20:
            raise ValueError("사용자명은 2~20자여야 합니다")
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("사용자명은 영문, 숫자, 밑줄만 사용할 수 있습니다")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다")
        return v


class RegisterData(BaseModel):
    user_id: str
    username: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LoginData(BaseModel):
    access_token: str
    refresh_token: str
    user_id: str
    username: str


class LogoutRequest(BaseModel):
    refresh_token: str


class KakaoLoginRequest(BaseModel):
    access_token: str


class KakaoLoginData(BaseModel):
    access_token: str
    refresh_token: str
    is_new_user: bool
    message: str | None = None


# ── 추가 엔드포인트 ──────────────────────────────────────────────────────────
class CheckUsernameData(BaseModel):
    username: str
    available: bool


class PasswordResetEmailRequest(BaseModel):
    email: EmailStr


class PasswordResetEmailData(BaseModel):
    sent: bool
    message: str | None = None


class PasswordResetRequest(BaseModel):
    token: str
    new_password: str


class PasswordResetData(BaseModel):
    success: bool


class WithdrawData(BaseModel):
    user_id: str
    success: bool


class RefreshData(BaseModel):
    access_token: str
    refresh_token: str
