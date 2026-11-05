"""어르신 기기 연결(기기 쿠키 발급)·권한 저장."""

from fastapi import APIRouter, Response
from sqlalchemy import select, update

from app.config import now_kst
from app.deps import DB, CurrentDevice
from app.errors import ApiError
from app.models import ElderDevice, FamilyRoom, Invite, Notification, RoomMember
from app.schemas.rooms import DeviceConnectIn, DeviceOut, PermissionsIn
from app.security import new_token, set_device_cookie, sha256_hex

router = APIRouter(prefix="/devices", tags=["devices"])


def _out(device: ElderDevice, room: FamilyRoom) -> DeviceOut:
    return DeviceOut(
        room_id=room.room_id,
        elder_name=room.elder_name,
        elder_honorific=room.elder_honorific,
        perm_mic=device.perm_mic,
        perm_camera=device.perm_camera,
        perm_notification=device.perm_notification,
        input_mode=device.input_mode,
    )


def notify_family(db, room_id: int, kind: str, title: str, body: str | None = None, link: str | None = None):
    """가족 구성원 모두에게 앱 내 알림 1건씩."""
    for uid in db.scalars(
        select(RoomMember.user_id).where(RoomMember.room_id == room_id, RoomMember.removed_at.is_(None))
    ):
        db.add(
            Notification(
                room_id=room_id,
                target_type="FAMILY",
                target_user_id=uid,
                kind=kind,
                title=title,
                body=body,
                link_screen=link,
            )
        )


@router.post("/connect", response_model=DeviceOut)
def connect(body: DeviceConnectIn, response: Response, db: DB):
    now = now_kst()
    # 소모는 UPDATE 한 문장 (동시 탭 2회 통과 방지, D16)
    row = db.execute(
        update(Invite)
        .where(
            Invite.token_hash == sha256_hex(body.token),
            Invite.kind == "ELDER_DEVICE",
            Invite.used_at.is_(None),
            Invite.revoked_at.is_(None),
            Invite.expires_at > now,
        )
        .values(used_at=now)
        .returning(Invite.room_id)
    ).first()
    if not row:
        raise ApiError(410, "INVITE_INVALID", "링크가 만료되었거나 이미 사용됐어요. 가족에게 새 링크를 받아 주세요")
    room_id = row[0]
    # 방당 활성 기기 1: 기존 기기는 폐기
    db.execute(
        update(ElderDevice)
        .where(ElderDevice.room_id == room_id, ElderDevice.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    raw = new_token()
    device = ElderDevice(room_id=room_id, device_token_hash=sha256_hex(raw))
    db.add(device)
    room = db.get(FamilyRoom, room_id)
    notify_family(db, room_id, "DEVICE_CONNECTED", f"{room.elder_name} 님 기기가 연결됐어요", link="GROUP_002")
    db.commit()
    db.refresh(device)
    set_device_cookie(response, raw)
    return _out(device, room)


@router.patch("/me/permissions", response_model=DeviceOut)
def set_permissions(body: PermissionsIn, device: CurrentDevice, db: DB):
    changed = body.model_dump(exclude_none=True)
    for key, value in changed.items():
        setattr(device, key, value)
    room = db.get(FamilyRoom, device.room_id)
    if any(v is False for v in changed.values()):
        off = ", ".join(k.removeprefix("perm_") for k, v in changed.items() if v is False)
        notify_family(db, room.room_id, "PERMISSION_OFF", f"{room.elder_name} 님 기기 권한이 꺼져 있어요", body=off)
    db.commit()
    return _out(device, room)
