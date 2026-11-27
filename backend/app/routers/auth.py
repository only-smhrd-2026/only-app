"""가족 가입·로그인 (이메일/비밀번호, 쿠키 session). 카카오는 2순위."""

import io
import logging
import uuid

from fastapi import APIRouter, Request, Response, UploadFile
from PIL import Image
from sqlalchemy import select

from app.config import UPLOAD_MAX_BYTES, now_kst
from app.deps import DB, CurrentUser
from app.errors import ApiError
from app.models import FamilyRoom, RoomMember, User
from app.routers.photos import to_jpeg
from app.schemas.auth import AuthOut, LoginIn, NameIn, PasswordChangeIn, SignupIn, UserOut
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
from app.services import storage

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)


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


PROFILE_SIDE = 400  # 프로필 사진 긴 변(px) — 동그라미로만 보이니 작게


@router.patch("/me", response_model=UserOut)
def update_me(body: NameIn, user: CurrentUser, db: DB):
    """내 이름 고치기 (11/27 내 정보). 일기·댓글 옆 이름은 읽을 때마다 users.name 을 쓰니 지난 글도 같이 바뀐다"""
    user.name = body.name
    db.commit()
    return user


@router.put("/me/photo", response_model=UserOut)
def set_my_photo(file: UploadFile, user: CurrentUser, db: DB, room_id: int | None = None):
    """이 가족방 프로필 사진을 올린다. 화면이 동그라미로 잘라 정사각형으로 보낸다."""
    member = _photo_member(db, user.user_id, room_id)
    key = f"rooms/{member.room_id}/profiles/{uuid.uuid4().hex}.jpg"
    storage.put(key, profile_jpeg(file))
    return _save_member_photo(db, user, member, key)


def profile_jpeg(file: UploadFile) -> bytes:
    """동그라미 사진(내 프로필·어르신 얼굴) — 사진 올리기와 같은 검사(to_jpeg — 위치정보 지움) 뒤 작게 줄인 JPEG"""
    if file.size is None or file.size > UPLOAD_MAX_BYTES:
        raise ApiError(400, "PHOTO_TOO_BIG", f"사진은 {UPLOAD_MAX_BYTES // (1024 * 1024)}MB까지예요")
    jpeg, _ = to_jpeg(file.file.read())
    img = Image.open(io.BytesIO(jpeg))
    img.thumbnail((PROFILE_SIDE, PROFILE_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


@router.delete("/me/photo", response_model=UserOut)
def delete_my_photo(user: CurrentUser, db: DB, room_id: int | None = None):
    """이 가족방의 프로필 사진을 지운다."""
    return _save_member_photo(db, user, _photo_member(db, user.user_id, room_id), None)


def _photo_member(db, user_id: int, room_id: int | None) -> RoomMember:
    query = (
        select(RoomMember)
        .join(FamilyRoom)
        .where(RoomMember.user_id == user_id, RoomMember.removed_at.is_(None), FamilyRoom.status == "ACTIVE")
        .with_for_update(of=RoomMember)
    )
    if room_id is not None:
        member = db.scalar(query.where(RoomMember.room_id == room_id))
        if member is None:
            raise ApiError(404, "ROOM_NOT_FOUND", "가족방을 찾을 수 없어요")
        return member
    # 예전 앱에서 가족방 번호 없이 보냈을 때는 대상 가족방이 하나인 경우만 받는다.
    members = db.scalars(query.limit(2)).all()
    if len(members) != 1:
        raise ApiError(409, "ROOM_REQUIRED", "가족방을 선택하고 내 정보에서 사진을 바꿔 주세요")
    return members[0]


def _save_member_photo(db, user: User, member: RoomMember, key: str | None) -> UserOut:
    old, member.profile_key = member.profile_key, key
    db.commit()
    # 예전 계정 사진 파일은 다른 가족방에서도 쓰일 수 있다. 계정 탈퇴 때 원본을 지운다.
    if old and storage.ROOM_PROFILE_KEY_RE.fullmatch(old):
        drop_photo(old)
    out = UserOut.model_validate(user)
    out.profile_url = f"/api/media/{key}" if key else None
    return out


def drop_photo(key: str) -> None:
    """옛 프로필 사진 파일 지우기. DB 저장 뒤라 실패해도 응답은 그대로 (photos.commit_photo_deletion 과 같은 순서)"""
    try:
        storage.delete(key)
    except Exception as e:  # 저장소 일시 오류 — 파일만 남는다. 로그는 예외 종류만 (D15)
        log.warning("profile photo delete failed error=%s", type(e).__name__)
