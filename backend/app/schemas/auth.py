from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 메일을 보내지 않으므로 모양만 검사 (email-validator 는 .local 같은 테스트 도메인을 거부해 쓰지 않음)
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignupIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE, max_length=255)
    password: str = Field(min_length=8, max_length=64)  # bcrypt 72바이트 상한 안
    name: str = Field(min_length=1, max_length=30)
    terms_agreed: Literal[True]  # 약관 동의 없이는 가입 불가 (NFR-AN-004)


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE, max_length=255)
    password: str = Field(max_length=64)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    email: str | None
    name: str
    login_type: str
    created_at: datetime


class AuthOut(BaseModel):
    user: UserOut
