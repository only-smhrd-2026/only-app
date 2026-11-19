"""가족 가입·로그인 (이메일/비밀번호, 쿠키 session). 카카오는 2순위."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.config import now_kst
from app.deps import DB, CurrentUser
from app.errors import ApiError
from app.models import User
from app.schemas.auth import AuthOut, LoginIn, PasswordChangeIn, SignupIn, UserOut
from app.schemas.common import OkOut
from app.security import (
    SESSION_COOKIE,
    clear_cookie,
    clear_login_failures,
    hash_password,
    login_allowed,
    reserve_login_attempt,
    set_session_cookie,
    signup_allowed,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=AuthOut, status_code=201)
def signup(body: SignupIn, request: Request, response: Response, db: DB):
    # 같은 주소에서 계정을 찍어 내지 못하게 (11/19) — 가입은 누구나 되고 가족 쪽 AI·음성 몫은 계정마다 쓸 수 있다
    if not signup_allowed(request.client.host if request.client else "unknown"):
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "잠시 후 다시 시도해 주세요")
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
    email = body.email.lower()
    # 이메일별 시도 칸을 비교 전에 먼저 잡는다 — 동시에 온 요청도 상한까지만 비교에 들어간다 (11/19 다듬기)
    if not login_allowed(ip) or not reserve_login_attempt(email):
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "잠시 후 다시 시도해 주세요")
    user = db.scalar(select(User).where(User.email == email, User.status == "ACTIVE"))
    # 실패 문구는 어느 경우든 같게 (계정 존재 여부 노출 방지, D20)
    # 계정이 없어도 비밀번호 비교(가짜 해시)를 한 번 — 걸린 시간도 같게 (security.verify_password)
    if not verify_password(body.password, user.password_hash if user else None) or not user:
        raise ApiError(401, "LOGIN_FAILED", "이메일 또는 비밀번호가 올바르지 않습니다")  # 잡은 칸이 실패로 남는다
    clear_login_failures(email)  # 맞았으니 이번에 잡은 칸까지 지운다
    user.last_login_at = now_kst()
    db.commit()
    set_session_cookie(response, user.user_id)
    return AuthOut(user=UserOut.model_validate(user))


@router.post("/logout", response_model=OkOut)
def logout(response: Response):
    clear_cookie(response, SESSION_COOKIE)
    return OkOut()


@router.post("/password", response_model=OkOut)
def change_password(body: PasswordChangeIn, request: Request, response: Response, user: CurrentUser, db: DB):
    ip = request.client.host if request.client else "unknown"
    if not login_allowed(ip):
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "잠시 후 다시 시도해 주세요")
    user = db.get(User, user.user_id, populate_existing=True, with_for_update=True)
    if user.email and not reserve_login_attempt(user.email):  # 로그인과 같은 셈 — 비교 전에 칸을 먼저 잡는다
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "잠시 후 다시 시도해 주세요")
    if not verify_password(body.current_password, user.password_hash):
        raise ApiError(400, "WRONG_PASSWORD", "지금 비밀번호가 맞지 않아요")
    if user.email:
        clear_login_failures(user.email)  # 지금 비밀번호가 맞았으니 잡은 칸을 지운다 (아래에서 거절돼도 실패가 아니다)
    if body.new_password == body.current_password:
        raise ApiError(400, "SAME_PASSWORD", "지금과 다른 비밀번호를 써 주세요")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    set_session_cookie(response, user.user_id)
    return OkOut()


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
