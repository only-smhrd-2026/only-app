"""가족방 생성·목록, 초대 링크 발급·조회·폐기 (방장만)."""

from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import distinct, func, select, update

from app.config import now_kst
from app.deps import DB, CurrentUser, require_owner
from app.errors import ApiError
from app.models import FamilyRoom, Invite, Photo, RoomMember
from app.schemas.common import OkOut
from app.schemas.rooms import InviteCreatedOut, InviteCreateIn, InviteOut, RoomCreateIn, RoomOut
from app.security import new_token, sha256_hex

router = APIRouter(prefix="/rooms", tags=["rooms"])

ELDER_DEVICE_MIN_PHOTOS = 3


def room_out(room: FamilyRoom, user_id: int) -> RoomOut:
    out = RoomOut.model_validate(room)
    out.is_owner = room.owner_user_id == user_id
    return out


@router.post("", response_model=RoomOut, status_code=201)
def create_room(body: RoomCreateIn, user: CurrentUser, db: DB):
    room = FamilyRoom(elder_name=body.elder_name, elder_honorific=body.elder_honorific, owner_user_id=user.user_id)
    db.add(room)
    db.flush()
    db.add(
        RoomMember(
            room_id=room.room_id,
            user_id=user.user_id,
            relation_tag=body.relation_tag,
            nickname=body.nickname,
        )
    )
    db.commit()
    db.refresh(room)
    return room_out(room, user.user_id)


@router.get("", response_model=list[RoomOut])
def list_rooms(user: CurrentUser, db: DB):
    rooms = db.scalars(
        select(FamilyRoom)
        .join(RoomMember, RoomMember.room_id == FamilyRoom.room_id)
        .where(
            RoomMember.user_id == user.user_id,
            RoomMember.removed_at.is_(None),
            FamilyRoom.status == "ACTIVE",
        )
        .order_by(FamilyRoom.room_id)
    ).all()
    return [room_out(r, user.user_id) for r in rooms]


@router.post("/{room_id}/invites", response_model=InviteCreatedOut, status_code=201)
def create_invite(room_id: int, body: InviteCreateIn, request: Request, user: CurrentUser, db: DB):
    require_owner(room_id, user, db)
    now = now_kst()
    if body.kind == "ELDER_DEVICE":
        n = db.scalar(
            select(func.count(distinct(Photo.object_key))).where(
                Photo.room_id == room_id, Photo.status == "ACTIVE", Photo.source == "FAMILY"
            )
        )
        if (n or 0) < ELDER_DEVICE_MIN_PHOTOS:
            raise ApiError(409, "NEED_PHOTOS", "사진을 3장 이상 올린 뒤에 어르신 기기를 연결할 수 있어요")
        # 새 기기 링크를 만들면 기존 활성 링크는 폐기 (D16: 방당 활성 기기 링크 1)
        db.execute(
            update(Invite)
            .where(
                Invite.room_id == room_id,
                Invite.kind == "ELDER_DEVICE",
                Invite.used_at.is_(None),
                Invite.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        expires_at, path = now + timedelta(hours=24), "elder/connect"
    else:
        expires_at, path = now + timedelta(days=7), "join"
    token = new_token()
    invite = Invite(
        room_id=room_id,
        kind=body.kind,
        token_hash=sha256_hex(token),
        expires_at=expires_at,
        created_by=user.user_id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    # 토큰은 # 뒤 → 서버 로그·Referer·미리보기 봇에 안 감 (D16). 이 응답 한 번만 원문을 보여 준다.
    base = str(request.base_url).rstrip("/")
    return InviteCreatedOut(
        invite_id=invite.invite_id, kind=invite.kind, url=f"{base}/{path}#{token}", expires_at=invite.expires_at
    )


@router.get("/{room_id}/invites", response_model=list[InviteOut])
def list_invites(room_id: int, user: CurrentUser, db: DB):
    require_owner(room_id, user, db)
    now = now_kst()
    return db.scalars(
        select(Invite)
        .where(
            Invite.room_id == room_id,
            Invite.revoked_at.is_(None),
            Invite.expires_at > now,
            (Invite.kind == "FAMILY") | (Invite.used_at.is_(None)),
        )
        .order_by(Invite.invite_id.desc())
    ).all()


@router.delete("/{room_id}/invites/{invite_id}", response_model=OkOut)
def revoke_invite(room_id: int, invite_id: int, user: CurrentUser, db: DB):
    require_owner(room_id, user, db)
    invite = db.get(Invite, invite_id)
    if not invite or invite.room_id != room_id:
        raise ApiError(404, "INVITE_NOT_FOUND", "링크를 찾을 수 없습니다")
    if invite.revoked_at is None:
        invite.revoked_at = now_kst()
        db.commit()
    return OkOut()
