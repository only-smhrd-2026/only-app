"""초대 링크 상태 확인(소모 없음)·가족 참여. 토큰은 항상 본문으로 (D15/D16: 쿼리스트링에 토큰 금지)."""

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import or_, select

from app.config import now_kst
from app.deps import DB, CurrentUser
from app.errors import ApiError
from app.models import FamilyRoom, RoomMember
from app.routers.rooms import INVITE_COLS, room_out
from app.schemas.rooms import DeviceConnectIn, InviteAcceptIn, InviteStatusOut, RoomOut
from app.security import sha256_hex

router = APIRouter(prefix="/invites", tags=["invites"])


def _find(db, token: str) -> tuple[FamilyRoom, str, datetime]:
    """토큰 → (가족방, 종류, 만료 시각). 링크는 family_rooms 칸에 있다 (D38). 새 링크로 덮어써진 옛 링크는 404."""
    h = sha256_hex(token)
    room = db.scalar(
        select(FamilyRoom).where(or_(FamilyRoom.family_invite_hash == h, FamilyRoom.elder_invite_hash == h))
    )
    if not room:
        raise ApiError(404, "INVITE_NOT_FOUND", "링크를 찾을 수 없습니다")
    kind = "FAMILY" if room.family_invite_hash == h else "ELDER_DEVICE"
    return room, kind, getattr(room, INVITE_COLS[kind][1])


# 쓸 수 있는 링크 = 만료 전. 가족 링크는 7일 동안 여러 번, 기기 링크는 쓰는 순간 만료를 지금으로 바꿔 1회 (D16, D38)
@router.post("/status", response_model=InviteStatusOut)
def invite_status(body: DeviceConnectIn, db: DB):
    room, kind, expires_at = _find(db, body.token)
    return InviteStatusOut(kind=kind, elder_name=room.elder_name, expires_at=expires_at, valid=expires_at > now_kst())


@router.post("/accept", response_model=RoomOut)
def accept_invite(body: InviteAcceptIn, user: CurrentUser, db: DB):
    room, kind, expires_at = _find(db, body.token)
    if kind != "FAMILY" or expires_at <= now_kst():
        raise ApiError(410, "INVITE_INVALID", "링크가 만료되었거나 사용할 수 없어요")
    member = db.scalar(select(RoomMember).where(RoomMember.room_id == room.room_id, RoomMember.user_id == user.user_id))
    if member and member.removed_at is not None:
        raise ApiError(403, "MEMBER_REMOVED", "이 가족방에서 내보내진 계정이에요")  # D16
    if not member:
        db.add(
            RoomMember(
                room_id=room.room_id,
                user_id=user.user_id,
                relation_tag=body.relation_tag,
                nickname=body.nickname,
            )
        )
    if body.name:
        user.name = body.name
    db.commit()
    return room_out(room, user.user_id)
