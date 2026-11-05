"""인증·권한 의존성 3종 (D2). 즉시 차단은 매 요청 DB 확인으로.

- current_user:   쿠키 session(JWT) → users.status='ACTIVE'
- current_device: 쿠키 device(토큰 원문) → elder_devices.revoked_at IS NULL
- require_member: room_members.removed_at IS NULL
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import now_kst
from app.db import get_db
from app.errors import ApiError
from app.models import ElderDevice, FamilyRoom, RoomMember, User
from app.security import DEVICE_COOKIE, SESSION_COOKIE, decode_session_jwt, sha256_hex

DB = Annotated[Session, Depends(get_db)]


def _user_from_cookie(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = decode_session_jwt(token) if token else None
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user if user and user.status == "ACTIVE" else None


def _device_from_cookie(request: Request, db: Session) -> ElderDevice | None:
    raw = request.cookies.get(DEVICE_COOKIE)
    if not raw:
        return None
    device = db.scalar(
        select(ElderDevice).where(ElderDevice.device_token_hash == sha256_hex(raw), ElderDevice.revoked_at.is_(None))
    )
    if device and (device.last_seen_at is None or now_kst() - device.last_seen_at > timedelta(minutes=5)):
        device.last_seen_at = now_kst()
        db.commit()
    return device


def current_user(request: Request, db: DB) -> User:
    user = _user_from_cookie(request, db)
    if not user:
        raise ApiError(401, "AUTH_REQUIRED", "로그인이 필요합니다")
    return user


def current_device(request: Request, db: DB) -> ElderDevice:
    device = _device_from_cookie(request, db)
    if not device:
        raise ApiError(401, "DEVICE_REQUIRED", "기기 연결이 필요합니다")
    return device


def current_actor(request: Request, db: DB) -> User | ElderDevice:
    """가족·어르신 공용 엔드포인트(/api/stt, /api/media)."""
    actor = _user_from_cookie(request, db) or _device_from_cookie(request, db)
    if not actor:
        raise ApiError(401, "AUTH_REQUIRED", "로그인 또는 기기 연결이 필요합니다")
    return actor


def require_member(room_id: int, user: User, db: Session) -> RoomMember:
    member = db.scalar(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.user_id == user.user_id,
            RoomMember.removed_at.is_(None),
        )
    )
    if not member:
        raise ApiError(403, "NOT_MEMBER", "이 가족방의 구성원이 아닙니다")
    return member


def require_owner(room_id: int, user: User, db: Session) -> FamilyRoom:
    require_member(room_id, user, db)
    room = db.get(FamilyRoom, room_id)
    if not room or room.owner_user_id != user.user_id:
        raise ApiError(403, "NOT_OWNER", "방장만 할 수 있습니다")
    return room


CurrentUser = Annotated[User, Depends(current_user)]
CurrentDevice = Annotated[ElderDevice, Depends(current_device)]
CurrentActor = Annotated[User | ElderDevice, Depends(current_actor)]
