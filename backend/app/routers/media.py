"""GET /api/media/{key} — 쿠키로 가족방 구성원/기기를 확인한 뒤 사진·그림일기 바이트 반환 (서명 URL 없음, D2/D18)."""

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.deps import DB, CurrentActor
from app.errors import ApiError
from app.models import Diary, FamilyRoom, Photo, RoomMember, User
from app.services import storage

router = APIRouter(prefix="/media", tags=["media"])
NOT_FOUND = ApiError(404, "MEDIA_NOT_FOUND", "사진을 찾을 수 없어요")  # 권한 없음도 같은 응답 (존재 여부 비노출)


@router.get("/{key:path}", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
def get_media(key: str, actor: CurrentActor, db: DB):
    if not storage.valid_key(key):
        raise NOT_FOUND
    profile = storage.PROFILE_KEY_RE.match(key)
    if profile:  # 프로필 사진 (11/27) — 지금 쓰는 사진이고, 나 자신이거나 같은 가족방 사람·그 방 어르신 기기만
        owner = db.get(User, int(profile[1]))
        if owner is None or owner.profile_key != key or not _shares_room(owner.user_id, actor, db):
            raise NOT_FOUND
        data = storage.get(key)
        if data is None:
            raise NOT_FOUND
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
    # 가족 목소리 답장 mp3 (D99) — key 의 가족방 번호로 권한을 본다. 답장을 지우거나 바꾸면 파일도 지워 없으면 404
    voice = storage.VOICE_KEY_RE.match(key)
    room_id = int(voice[1]) if voice else None
    if room_id is None:
        room_id = db.scalar(
            select(Photo.room_id).where((Photo.object_key == key) | (Photo.thumb_key == key), Photo.status == "ACTIVE")
        )
    if room_id is None:  # 그림일기 그림 — 게시된 일기의 것만 (D36)
        room_id = db.scalar(select(Diary.room_id).where(Diary.illustration_key == key, Diary.status == "POSTED"))
    if room_id is None:
        raise NOT_FOUND
    if isinstance(actor, FamilyRoom):  # 어르신 기기 = 연결된 가족방 (D38)
        allowed = actor.room_id == room_id
    else:
        allowed = (
            db.scalar(
                select(RoomMember.member_id).where(
                    RoomMember.room_id == room_id,
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
    media_type = "audio/mpeg" if voice else "image/jpeg"
    return Response(data, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


def _shares_room(user_id: int, actor, db) -> bool:
    """user_id 가 actor(가족 또는 어르신 기기)와 같은 가족방에 지금 있는지."""
    if not isinstance(actor, FamilyRoom) and actor.user_id == user_id:
        return True
    rooms = select(RoomMember.room_id).where(RoomMember.user_id == user_id, RoomMember.removed_at.is_(None))
    if isinstance(actor, FamilyRoom):
        return actor.room_id in db.scalars(rooms).all()
    return (
        db.scalar(
            select(RoomMember.member_id).where(
                RoomMember.user_id == actor.user_id, RoomMember.removed_at.is_(None), RoomMember.room_id.in_(rooms)
            )
        )
        is not None
    )
