"""어르신 기기 연결(기기 쿠키 발급)·권한 저장. 기기 정보는 family_rooms 의 device_ 칸 (가족방당 1대, D38)."""

from fastapi import APIRouter, Response
from sqlalchemy import select, update

from app.config import now_kst
from app.deps import DB, CurrentDevice
from app.errors import ApiError
from app.models import FamilyRoom, Notification, RoomMember
from app.schemas.rooms import DeviceConnectIn, DeviceOut, PermissionsIn
from app.security import new_token, set_device_cookie, sha256_hex
from app.services import push

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


def notify_family(
    db, room_id: int, kind: str, title: str, body: str | None = None, link: str | None = None, *, to_phone: bool = True
):
    """가족 구성원 모두에게 앱 내 알림 1건씩. 일기·주간 이야기·위급 알림은 폰 푸시로도 (services/push.py).

    to_phone=False 면 알림 목록에만 남긴다 — 날마다 되풀이되는 알림이 폰을 날마다 울리지 않게
    (scheduler.no_record_alerts).
    """
    uids = db.scalars(
        select(RoomMember.user_id).where(RoomMember.room_id == room_id, RoomMember.removed_at.is_(None))
    ).all()
    for uid in uids:
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
    if to_phone:
        push.queue_family(db, uids, room_id, kind, title, body, link)


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
    push.forget_room(db, room.room_id)  # 옛 기기의 푸시 구독 — 새 기기는 연결 화면에서 새로 등록한다
    notify_family(db, room.room_id, "DEVICE_CONNECTED", f"{room.elder_name} 님 기기가 연결됐어요", link="GROUP_002")
    db.commit()
    set_device_cookie(response, raw)
    return _out(room)


@router.get("/me", response_model=DeviceOut)
def me(room: CurrentDevice):
    """이 폰이 어르신 기기로 연결돼 있는지 — 홈 화면 아이콘으로 열 때(/start, D68) 어르신 홈으로 보낼지 가린다.
    읽기만 한다(어르신 홈 GET /api/elder/home 은 오늘 사진을 보여 준 수를 올린다)."""
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
        notify_family(
            db,
            room.room_id,
            "PERMISSION_OFF",
            f"{room.elder_name} 님 기기 권한이 꺼져 있어요",
            body=off,
            link="GROUP_002",
        )
    db.commit()
    return _out(room)
