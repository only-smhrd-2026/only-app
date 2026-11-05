"""가족 가입·로그인 (이메일/비밀번호, 쿠키 session). 카카오는 2순위."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.config import now_kst
from app.deps import DB, CurrentUser
from app.errors import ApiError
from app.models import User
from app.schemas.auth import AuthOut, LoginIn, SignupIn, UserOut
from app.schemas.common import OkOut
from app.security import (
    SESSION_COOKIE,
    clear_cookie,
    hash_password,
    login_allowed,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthOut, status_code=201)
def signup(body: SignupIn, response: Response, db: DB):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ApiError(409, "EMAIL_TAKEN", "이미 가입된 이메일입니다")
    user = User(
        login_type="EMAIL",
        email=email,
        password_hash=hash_password(body.password),
        name=body.name,
        terms_agreed_at=now_kst(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    set_session_cookie(response, user.user_id)
    return AuthOut(user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, request: Request, response: Response, db: DB):
    ip = request.client.host if request.client else "unknown"
    if not login_allowed(ip):
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "잠시 후 다시 시도해 주세요")
    user = db.scalar(select(User).where(User.email == body.email.lower(), User.status == "ACTIVE"))
    # 실패 문구는 어느 경우든 같게 (계정 존재 여부 노출 방지, D20)
    if not user or not verify_password(body.password, user.password_hash):
        raise ApiError(401, "LOGIN_FAILED", "이메일 또는 비밀번호가 올바르지 않습니다")
    user.last_login_at = now_kst()
    db.commit()
    set_session_cookie(response, user.user_id)
    return AuthOut(user=UserOut.model_validate(user))


@router.post("/logout", response_model=OkOut)
def logout(response: Response):
    clear_cookie(response, SESSION_COOKIE)
    return OkOut()


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
