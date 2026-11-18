from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

# 메일을 보내지 않으므로 모양만 검사 (email-validator 는 .local 같은 테스트 도메인을 거부해 쓰지 않음)
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _bcrypt_bytes(value: str) -> str:
    if len(value.encode()) > 72:
        raise ValueError("비밀번호가 너무 길어요")
    return value


NewPassword = Annotated[str, Field(min_length=8, max_length=64), AfterValidator(_bcrypt_bytes)]


class SignupIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE, max_length=255)
    password: NewPassword
    name: str = Field(min_length=1, max_length=30)
    terms_agreed: Literal[True]  # 약관 동의 없이는 가입 불가 (NFR-AN-004)


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_RE, max_length=255)
    password: str = Field(max_length=64)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=64)
    new_password: NewPassword


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: int
    email: str | None
    name: str
    login_type: str
    created_at: datetime


class AuthOut(BaseModel):
    user: UserOut
