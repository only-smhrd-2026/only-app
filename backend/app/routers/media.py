"""GET /api/media/{key} — 쿠키로 가족방 구성원/기기를 확인한 뒤 사진 바이트 반환 (서명 URL 없음, D2/D18)."""

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.deps import DB, CurrentActor
from app.errors import ApiError
from app.models import ElderDevice, Photo, RoomMember
from app.services import storage

router = APIRouter(prefix="/media", tags=["media"])
NOT_FOUND = ApiError(404, "MEDIA_NOT_FOUND", "사진을 찾을 수 없어요")  # 권한 없음도 같은 응답 (존재 여부 비노출)


@router.get("/{key:path}", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
def get_media(key: str, actor: CurrentActor, db: DB):
    if not storage.valid_key(key):
        raise NOT_FOUND
    photo = db.scalar(
        select(Photo).where((Photo.object_key == key) | (Photo.thumb_key == key), Photo.status == "ACTIVE")
    )
    if not photo:
        raise NOT_FOUND
    if isinstance(actor, ElderDevice):
        allowed = actor.room_id == photo.room_id
    else:
        allowed = (
            db.scalar(
                select(RoomMember.member_id).where(
                    RoomMember.room_id == photo.room_id,
                    RoomMember.user_id == actor.user_id,
                    RoomMember.removed_at.is_(None),
                )
            )
            is not None
        )
    if not allowed:
        raise NOT_FOUND
    data = storage.get(key)
    if data is None:
        raise NOT_FOUND
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
