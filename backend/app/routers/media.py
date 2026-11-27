"""GET /api/media/{key} — 쿠키로 가족방 구성원/기기를 확인한 뒤 사진·그림일기 바이트 반환 (서명 URL 없음, D2/D18)."""

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.deps import DB, CurrentActor
from app.errors import ApiError
from app.models import Diary, FamilyRoom, Photo, RoomMember
from app.services import storage

router = APIRouter(prefix="/media", tags=["media"])
NOT_FOUND = ApiError(404, "MEDIA_NOT_FOUND", "사진을 찾을 수 없어요")  # 권한 없음도 같은 응답 (존재 여부 비노출)


@router.get("/{key:path}", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
def get_media(key: str, actor: CurrentActor, db: DB):
    if not storage.valid_key(key):
        raise NOT_FOUND
    room_profile = storage.ROOM_PROFILE_KEY_RE.fullmatch(key)
    legacy_profile = storage.PROFILE_KEY_RE.fullmatch(key)
    if room_profile or legacy_profile:
        rooms = (
            select(RoomMember.room_id)
            .join(FamilyRoom)
            .where(RoomMember.profile_key == key, RoomMember.removed_at.is_(None), FamilyRoom.status == "ACTIVE")
        )
        if room_profile:
            rooms = rooms.where(RoomMember.room_id == int(room_profile[1]))
        elif legacy_profile:
            rooms = rooms.where(RoomMember.user_id == int(legacy_profile[1]))
        if not _can_read_profile(rooms, actor, db):
            raise NOT_FOUND
        data = storage.get(key)
        if data is None:
            raise NOT_FOUND
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
    # 가족 목소리 답장 mp3 (D99) — key 의 가족방 번호로 권한을 본다. 답장을 지우거나 바꾸면 파일도 지워 없으면 404
    voice = storage.VOICE_KEY_RE.match(key)
    # 어르신 얼굴 사진 (11/27) 도 key 의 가족방 번호로. 바꾸거나 지우면 옛 파일은 지워져 404
    by_room = voice or storage.ELDER_PHOTO_KEY_RE.match(key)
    room_id = int(by_room[1]) if by_room else None
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


def _can_read_profile(rooms, actor, db) -> bool:
    """이 사진을 쓰는 방에 가족 또는 어르신 기기가 지금 있는지 확인한다."""
    if isinstance(actor, FamilyRoom):
        return db.scalar(rooms.where(RoomMember.room_id == actor.room_id).limit(1)) is not None
    return (
        db.scalar(
            select(RoomMember.member_id)
            .where(RoomMember.user_id == actor.user_id, RoomMember.removed_at.is_(None), RoomMember.room_id.in_(rooms))
            .limit(1)
        )
        is not None
    )
