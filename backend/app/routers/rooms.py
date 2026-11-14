"""가족방 생성·목록, 초대 링크 발급·조회·폐기 (방장만). 어르신 기기 연결 해제."""

from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Request
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.config import now_kst
from app.deps import DB, CurrentUser, require_member, require_owner
from app.errors import ApiError
from app.models import FamilyRoom, Photo, RoomMember, User
from app.schemas.common import OkOut
from app.schemas.rooms import (
    InviteCreatedOut,
    InviteCreateIn,
    InviteKind,
    InviteOut,
    MemberOut,
    RoomCreateIn,
    RoomOut,
    RoomSettingsIn,
)
from app.security import new_token, sha256_hex

router = APIRouter(prefix="/rooms", tags=["rooms"])

ELDER_DEVICE_MIN_PHOTOS = 3
# 링크 종류 → family_rooms 칸 (해시, 만료). 종류마다 링크 1개 (D38). routers/invites.py 도 쓴다
INVITE_COLS = {
    "FAMILY": ("family_invite_hash", "family_invite_expires_at"),
    "ELDER_DEVICE": ("elder_invite_hash", "elder_invite_expires_at"),
}


def family_photo_count(db: Session, room_id: int) -> int:
    """가족이 올린 사진 수(지운 것 빼고, 같은 사진은 1장). 기기 링크 조건과 가족 홈 '시작 3단계'(D70)가 같이 쓴다."""
    return db.scalar(
        select(func.count(distinct(Photo.object_key))).where(
            Photo.room_id == room_id, Photo.status == "ACTIVE", Photo.source == "FAMILY"
        )
    )


def room_out(room: FamilyRoom, user_id: int, db: Session) -> RoomOut:
    out = RoomOut.model_validate(room)
    out.is_owner = room.owner_user_id == user_id
    # ponytail: 가족방마다 셈 2번(목록이면 방 수만큼) — 한 사람의 가족방은 몇 개뿐. 늘면 group_by 한 번으로
    out.photo_count = family_photo_count(db, room.room_id)
    out.member_count = db.scalar(
        select(func.count(RoomMember.member_id)).where(
            RoomMember.room_id == room.room_id, RoomMember.removed_at.is_(None)
        )
    )
    out.device_connected = room.device_token_hash is not None
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
    return room_out(room, user.user_id, db)


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
    return [room_out(r, user.user_id, db) for r in rooms]


@router.get("/{room_id}/members", response_model=list[MemberOut])
def list_members(room_id: int, user: CurrentUser, db: DB):
    """구성원 목록 (GROUP_002 ④, FR-AD-007). 구성원이면 누구나, 내보낸 사람은 빼고 들어온 순서."""
    require_member(room_id, user, db)
    owner_user_id = db.get(FamilyRoom, room_id).owner_user_id
    rows = db.execute(
        select(RoomMember, User.name)
        .join(User, User.user_id == RoomMember.user_id)
        .where(RoomMember.room_id == room_id, RoomMember.removed_at.is_(None))
        .order_by(RoomMember.joined_at, RoomMember.member_id)
    ).all()
    # 다른 가족에게 보이는 목록이라 이메일·로그인 방식은 넣지 않는다
    return [
        MemberOut(
            user_id=member.user_id,
            name=name,
            nickname=member.nickname,
            relation_tag=member.relation_tag,
            joined_at=member.joined_at,
            is_owner=member.user_id == owner_user_id,
        )
        for member, name in rows
    ]


@router.post("/{room_id}/invites", response_model=InviteCreatedOut, status_code=201)
def create_invite(room_id: int, body: InviteCreateIn, request: Request, user: CurrentUser, db: DB):
    room = require_owner(room_id, user, db)
    now = now_kst()
    if body.kind == "ELDER_DEVICE":
        if family_photo_count(db, room_id) < ELDER_DEVICE_MIN_PHOTOS:
            raise ApiError(409, "NEED_PHOTOS", "사진을 3장 이상 올린 뒤에 어르신 기기를 연결할 수 있어요")
        expires_at, path = now + timedelta(hours=24), "elder/connect"
    else:
        expires_at, path = now + timedelta(days=7), "join"
    # 칸을 덮어쓰므로 같은 종류의 이전 링크는 바로 무효 (D16 방당 기기 링크 1, D38 가족 링크도 1)
    token = new_token()
    hash_col, exp_col = INVITE_COLS[body.kind]
    setattr(room, hash_col, sha256_hex(token))
    setattr(room, exp_col, expires_at)
    db.commit()
    # 토큰은 # 뒤 → 서버 로그·Referer·미리보기 봇에 안 감 (D16). 이 응답 한 번만 원문을 보여 준다.
    base = str(request.base_url).rstrip("/")
    return InviteCreatedOut(kind=body.kind, url=f"{base}/{path}#{token}", expires_at=expires_at)


@router.get("/{room_id}/invites", response_model=list[InviteOut])
def list_invites(room_id: int, user: CurrentUser, db: DB):
    """아직 쓸 수 있는 링크 (종류마다 최대 1개)."""
    room = require_owner(room_id, user, db)
    now = now_kst()
    alive = {kind: getattr(room, exp_col) for kind, (_, exp_col) in INVITE_COLS.items()}
    return [InviteOut(kind=kind, expires_at=exp) for kind, exp in alive.items() if exp and exp > now]


@router.delete("/{room_id}/invites/{kind}", response_model=OkOut)
def revoke_invite(room_id: int, kind: InviteKind, user: CurrentUser, db: DB):
    """폐기 = 만료 시각을 지금으로 (해시는 남겨 링크를 열면 '더 쓸 수 없어요' 안내, D38)."""
    room = require_owner(room_id, user, db)
    _, exp_col = INVITE_COLS[kind]
    now = now_kst()
    expires_at = getattr(room, exp_col)
    if expires_at and expires_at > now:
        setattr(room, exp_col, now)
        db.commit()
    return OkOut()


@router.delete("/{room_id}/device", response_model=OkOut)
def revoke_device(room_id: int, user: CurrentUser, db: DB):
    """해제 = 기기 해시를 비움, 다시 쓰려면 새 어르신 기기용 링크(FR-AD-008)."""
    room = require_owner(room_id, user, db)
    if room.device_token_hash is not None:
        room.device_token_hash = None
        room.device_push_token = None
        room.device_connected_at = None
        room.device_last_seen_at = None
        db.commit()
    return OkOut()


@router.patch("/{room_id}/settings", response_model=RoomOut)
def update_settings(room_id: int, body: RoomSettingsIn, user: CurrentUser, db: DB):
    room = require_owner(room_id, user, db)
    changed = body.model_dump(exclude_none=True)
    memory_time = changed.get("memory_time")
    if memory_time and (memory_time.minute or memory_time.second or memory_time.microsecond):
        raise ApiError(422, "VALIDATION", "추억 시간은 정각으로 골라 주세요")
    if "tts_speed" in changed:
        changed["tts_speed"] = Decimal(changed["tts_speed"])
    for key, value in changed.items():
        setattr(room, key, value)
    db.commit()
    return room_out(room, user.user_id, db)


@router.delete("/{room_id}/members/{user_id}", response_model=OkOut)
def remove_member(room_id: int, user_id: int, user: CurrentUser, db: DB):
    room = require_owner(room_id, user, db)
    if user_id == room.owner_user_id:
        raise ApiError(400, "CANNOT_REMOVE_OWNER", "방장은 내보낼 수 없어요")
    member = db.scalar(
        select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == user_id).with_for_update()
    )
    if member is None:
        raise ApiError(404, "MEMBER_NOT_FOUND", "구성원을 찾을 수 없어요")
    if member.removed_at is None:
        member.removed_at = now_kst()
        db.commit()
    return OkOut()
