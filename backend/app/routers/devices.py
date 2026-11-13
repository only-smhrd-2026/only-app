"""어르신 기기 연결(기기 쿠키 발급)·권한 저장. 기기 정보는 family_rooms 의 device_ 칸 (가족방당 1대, D38)."""

from fastapi import APIRouter, Response
from sqlalchemy import select, update

from app.config import now_kst
from app.deps import DB, CurrentDevice
from app.errors import ApiError
from app.models import FamilyRoom, Notification, RoomMember
from app.schemas.rooms import DeviceConnectIn, DeviceOut, PermissionsIn
from app.security import new_token, set_device_cookie, sha256_hex

router = APIRouter(prefix="/devices", tags=["devices"])


def _out(room: FamilyRoom) -> DeviceOut:
    return DeviceOut(
        room_id=room.room_id,
        elder_name=room.elder_name,
        elder_honorific=room.elder_honorific,
        perm_mic=room.device_perm_mic,
        perm_camera=room.device_perm_camera,
        perm_notification=room.device_perm_notification,
        input_mode=room.device_input_mode,
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
    raw = new_token()
    # 링크 소모 + 새 기기 등록을 UPDATE 한 문장으로 (동시 탭 2회 통과 방지, D16).
    # 기기 해시를 덮어쓰므로 이전 기기는 바로 막힌다(가족방당 1대). 권한·입력 모드는 새 기기 기준으로 처음 값 (D38)
    row = db.execute(
        update(FamilyRoom)
        .where(FamilyRoom.elder_invite_hash == sha256_hex(body.token), FamilyRoom.elder_invite_expires_at > now)
        .values(
            elder_invite_expires_at=now,
            device_token_hash=sha256_hex(raw),
            device_push_token=None,
            device_perm_notification=False,
            device_perm_mic=False,
            device_perm_camera=False,
            device_input_mode="VOICE",
            device_connected_at=now,
            device_last_seen_at=None,
        )
        .returning(FamilyRoom.room_id)
    ).first()
    if not row:
        raise ApiError(410, "INVITE_INVALID", "링크가 만료되었거나 이미 사용됐어요. 가족에게 새 링크를 받아 주세요")
    room = db.get(FamilyRoom, row[0])
    notify_family(db, room.room_id, "DEVICE_CONNECTED", f"{room.elder_name} 님 기기가 연결됐어요", link="GROUP_002")
    db.commit()
    set_device_cookie(response, raw)
    return _out(room)


@router.patch("/me/permissions", response_model=DeviceOut)
def set_permissions(body: PermissionsIn, room: CurrentDevice, db: DB):
    changed = body.model_dump(exclude_none=True)
    for key, value in changed.items():
        setattr(room, f"device_{key}", value)  # perm_mic → device_perm_mic
    if any(v is False for v in changed.values()):
        # 가족 알림 목록에 그대로 보이는 글이라 칸 이름(mic) 대신 한글로
        names = {"perm_mic": "마이크", "perm_camera": "카메라", "perm_notification": "알림"}
        off = ", ".join(names[k] for k, v in changed.items() if v is False)
        notify_family(db, room.room_id, "PERMISSION_OFF", f"{room.elder_name} 님 기기 권한이 꺼져 있어요", body=off)
    db.commit()
    return _out(room)
