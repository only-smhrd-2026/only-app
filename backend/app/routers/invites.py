"""초대 링크 상태 확인(소모 없음)·가족 참여. 토큰은 항상 본문으로 (D15/D16: 쿼리스트링에 토큰 금지)."""

from fastapi import APIRouter
from sqlalchemy import select

from app.config import now_kst
from app.deps import DB, CurrentUser
from app.errors import ApiError
from app.models import FamilyRoom, Invite, RoomMember
from app.routers.rooms import room_out
from app.schemas.rooms import DeviceConnectIn, InviteAcceptIn, InviteStatusOut, RoomOut
from app.security import sha256_hex

router = APIRouter(prefix="/invites", tags=["invites"])


def _find(db, token: str) -> Invite:
    invite = db.scalar(select(Invite).where(Invite.token_hash == sha256_hex(token)))
    if not invite:
        raise ApiError(404, "INVITE_NOT_FOUND", "링크를 찾을 수 없습니다")
    return invite


def _is_valid(invite: Invite) -> bool:
    if invite.revoked_at is not None or invite.expires_at <= now_kst():
        return False
    return invite.kind == "FAMILY" or invite.used_at is None  # FAMILY 는 7일 다회, 기기는 1회


@router.post("/status", response_model=InviteStatusOut)
def invite_status(body: DeviceConnectIn, db: DB):
    invite = _find(db, body.token)
    room = db.get(FamilyRoom, invite.room_id)
    return InviteStatusOut(
        kind=invite.kind, elder_name=room.elder_name, expires_at=invite.expires_at, valid=_is_valid(invite)
    )


@router.post("/accept", response_model=RoomOut)
def accept_invite(body: InviteAcceptIn, user: CurrentUser, db: DB):
    invite = _find(db, body.token)
    if invite.kind != "FAMILY" or not _is_valid(invite):
        raise ApiError(410, "INVITE_INVALID", "링크가 만료되었거나 사용할 수 없어요")
    member = db.scalar(
        select(RoomMember).where(RoomMember.room_id == invite.room_id, RoomMember.user_id == user.user_id)
    )
    if member and member.removed_at is not None:
        raise ApiError(403, "MEMBER_REMOVED", "이 가족방에서 내보내진 계정이에요")  # D16
    if not member:
        db.add(
            RoomMember(
                room_id=invite.room_id,
                user_id=user.user_id,
                relation_tag=body.relation_tag,
                nickname=body.nickname,
            )
        )
    if body.name:
        user.name = body.name
    if invite.used_at is None:
        invite.used_at = now_kst()
    db.commit()
    room = db.get(FamilyRoom, invite.room_id)
    return room_out(room, user.user_id)
