"""어르신 홈·오늘의 한 장·사진첩 (기기 쿠키)."""

from fastapi import APIRouter
from sqlalchemy import exists, func, select

from app.config import now_kst, today_kst
from app.deps import DB, CurrentDevice
from app.models import Diary, DiaryRead, FamilyRoom, Photo
from app.schemas.common import OkOut
from app.schemas.elder import AlbumOut, AlbumPhotoOut, ElderHomeOut, ElderSettingsOut, TodayPickOut
from app.services import picks

router = APIRouter(prefix="/elder", tags=["elder"])


def _greeting(room: FamilyRoom) -> str:
    hour = now_kst().hour
    part = "좋은 아침이에요" if hour < 12 else ("좋은 오후예요" if hour < 18 else "좋은 저녁이에요")
    return f"{room.elder_name} {room.elder_honorific}, {part}."


@router.get("/home", response_model=ElderHomeOut)
def home(device: CurrentDevice, db: DB):
    room = db.get(FamilyRoom, device.room_id)
    today = today_kst()
    pick = picks.today_pick(db, room.room_id, today)
    if pick is None and now_kst().time() >= room.memory_time:
        pick = picks.select_pick(db, room.room_id, today)  # 09:00 잡을 놓쳤을 때 지연 보정 (D9)
    today_pick = None
    if pick:
        if pick.status == "PENDING":
            pick.shown_count += 1
            db.commit()
        photo = db.get(Photo, pick.photo_id)
        today_pick = TodayPickOut(
            pick_id=pick.pick_id,
            photo_id=pick.photo_id,
            photo_url=f"/api/media/{photo.object_key}",
            status=pick.status,
        )
    unread = db.scalar(
        select(func.count())
        .select_from(Diary)
        .where(
            Diary.room_id == room.room_id,
            Diary.author_type == "FAMILY",
            Diary.status == "POSTED",
            ~exists().where(DiaryRead.diary_id == Diary.diary_id, DiaryRead.reader_type == "ELDER"),
        )
    )
    return ElderHomeOut(
        greeting=_greeting(room),
        elder_name=room.elder_name,
        elder_honorific=room.elder_honorific,
        today_pick=today_pick,
        unread_family_news=unread or 0,
        settings=ElderSettingsOut(font_size=room.font_size, tts_speed=room.tts_speed, input_mode=device.input_mode),
    )


@router.post("/picks/today/listened", response_model=OkOut)
def listened(device: CurrentDevice, db: DB):
    pick = picks.today_pick(db, device.room_id, today_kst())
    if pick and pick.listened_at is None:
        pick.listened_at = now_kst()
        db.commit()
    return OkOut()


@router.post("/picks/today/skip", response_model=OkOut)
def skip(device: CurrentDevice, db: DB):
    """오늘의 한 장 건너뛰기 — 당일 다시 안 뜸. TODO(천주웅): 같은 사진 2회 건너뛰면 PICK_SKIPPED_2X 가족 알림."""
    pick = picks.today_pick(db, device.room_id, today_kst())
    if pick and pick.status == "PENDING":
        pick.status = "SKIPPED"
        pick.skipped_at = now_kst()
        db.commit()
    return OkOut()


@router.get("/album", response_model=AlbumOut)
def album(device: CurrentDevice, db: DB):
    """어르신 사진첩 목록 — 초석에서는 시드 사진이 그대로 나온다. 세부(2열 격자·일기 섞기)는 천주웅."""
    photos = db.scalars(
        select(Photo)
        .where(
            Photo.room_id == device.room_id,
            Photo.status == "ACTIVE",
            Photo.source.in_(["FAMILY", "ELDER_CAMERA"]),
        )
        .order_by(Photo.uploaded_at.desc(), Photo.photo_id.desc())
        .limit(100)
    ).all()
    return AlbumOut(
        photos=[
            AlbumPhotoOut(photo_id=p.photo_id, url=f"/api/media/{p.object_key}", taken_at=p.taken_at, caption=p.caption)
            for p in photos
        ]
    )
