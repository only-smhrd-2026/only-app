"""어르신 홈·오늘의 한 장·사진첩 (기기 쿠키)."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, update
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect

from app.config import (
    PHOTO_LIST_LIMIT,
    PICK_SKIP_ALERT,
    UPLOAD_LOCK_WAIT_SEC,
    UPLOAD_MAX_BYTES,
    now_kst,
    today_kst,
)
from app.deps import DB, CurrentDevice
from app.errors import ApiError
from app.models import DailyPick, Diary, FamilyRoom, Photo
from app.routers.devices import notify_family
from app.routers.photos import _UPLOAD_BODY, _upload_lock, photo_out, to_jpeg
from app.schemas.common import OkOut
from app.schemas.elder import AlbumOut, AlbumPhotoOut, ElderHomeOut, ElderSettingsOut, TodayPickOut
from app.schemas.photos import PhotoOut
from app.services import picks, storage

router = APIRouter(prefix="/elder", tags=["elder"])


def _device_first(device: CurrentDevice, db: DB) -> None:
    """기기를 확인한 뒤 본문 수신·잠금 대기 전에 DB 연결을 돌려준다 (D17)."""
    db.close()


async def _camera_form(request: Request, _: Annotated[None, Depends(_device_first)]) -> AsyncIterator[FormData]:
    """연결된 기기에서 사진 한 장과 재전송 번호만 받는다."""
    try:
        form = await request.form(max_files=1, max_fields=1)
    except HTTPException as e:
        if str(e.detail).startswith("Too many files"):
            raise ApiError(400, "TOO_MANY_PHOTOS", "사진은 한 번에 1장만 올려요") from None
        raise
    except ClientDisconnect:
        raise ApiError(400, "UPLOAD_CUT", "사진을 다 받지 못했어요. 다시 올려 주세요") from None
    try:
        yield form
    finally:
        await form.close()


@router.post("/photos", response_model=PhotoOut, status_code=201, openapi_extra=_UPLOAD_BODY)
def camera_photo(device: CurrentDevice, db: DB, form: Annotated[FormData, Depends(_camera_form)]):
    """카메라 사진을 JPEG 로 저장하고 같은 요청 번호의 재전송은 기존 사진을 돌려준다."""
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
    if not files:
        raise ApiError(422, "VALIDATION", "사진을 골라 주세요")
    raw = form.get("upload_batch_id")
    try:
        upload_batch_id = uuid.UUID(str(raw)) if raw else None
    except ValueError:
        raise ApiError(422, "VALIDATION", "입력값이 올바르지 않습니다") from None
    photo_file = files[0]
    if photo_file.size is None or photo_file.size > UPLOAD_MAX_BYTES:
        raise ApiError(400, "PHOTO_TOO_BIG", f"한 장은 {UPLOAD_MAX_BYTES // (1024 * 1024)}MB까지예요")
    if not _upload_lock.acquire(timeout=UPLOAD_LOCK_WAIT_SEC):
        raise ApiError(503, "UPLOAD_BUSY", "다른 사진을 올리는 중이에요. 잠시 뒤 다시 올려 주세요")
    try:
        if upload_batch_id:
            done = db.scalar(
                select(Photo)
                .where(Photo.room_id == device.room_id, Photo.upload_batch_id == upload_batch_id)
                .order_by(Photo.photo_id)
            )
            if done:
                return photo_out(done)
        jpeg, taken_at = to_jpeg(photo_file.file.read())
        batch_id = upload_batch_id or uuid.uuid4()
        key = f"rooms/{device.room_id}/{batch_id}/0.jpg"
        storage.put(key, jpeg)
        photo = Photo(
            room_id=device.room_id,
            uploaded_by=None,
            upload_batch_id=batch_id,
            object_key=key,
            taken_at=taken_at,
            source="ELDER_CAMERA",
        )
        db.add(photo)
        db.commit()
    finally:
        _upload_lock.release()
    return photo_out(photo)


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
        pick = picks.select_pick(db, room.room_id, today)  # 매시 정각 잡보다 먼저 열었거나 잡이 놓쳤을 때 보정 (D9)
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
            Diary.elder_read_at.is_(None),
        )
    )
    return ElderHomeOut(
        greeting=_greeting(room),
        elder_name=room.elder_name,
        elder_honorific=room.elder_honorific,
        today_pick=today_pick,
        unread_family_news=unread or 0,
        settings=ElderSettingsOut(
            font_size=room.font_size, tts_speed=room.tts_speed, input_mode=room.device_input_mode
        ),
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
    """오늘의 한 장을 건너뛰고, 같은 사진의 두 번째 건너뛰기에 가족에게 알린다."""
    # 상태 변경과 확인을 한 문장으로 처리해 중복 요청도 한 번만 센다.
    photo_id = db.scalar(
        update(DailyPick)
        .where(
            DailyPick.room_id == device.room_id,
            DailyPick.pick_date == today_kst(),
            DailyPick.status == "PENDING",
        )
        .values(status="SKIPPED", skipped_at=now_kst())
        .returning(DailyPick.photo_id)
    )
    if photo_id is not None:
        skipped_count = db.scalar(
            select(func.count())
            .select_from(DailyPick)
            .where(
                DailyPick.room_id == device.room_id,
                DailyPick.photo_id == photo_id,
                DailyPick.skipped_at.is_not(None),  # 건너뛴 기록 — 나중에 대화로 COMPLETED 가 되어도 줄지 않음
            )
        )
        if skipped_count == PICK_SKIP_ALERT:
            room = db.get(FamilyRoom, device.room_id)
            notify_family(db, device.room_id, "PICK_SKIPPED_2X", f"{room.elder_name} 님이 같은 사진을 두 번 넘기셨어요")
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
        .limit(PHOTO_LIST_LIMIT)  # 가족 사진 목록(routers/photos.py list_photos)과 같은 조건·순서·상한
    ).all()
    return AlbumOut(
        photos=[
            AlbumPhotoOut(photo_id=p.photo_id, url=f"/api/media/{p.object_key}", taken_at=p.taken_at, caption=p.caption)
            for p in photos
        ]
    )
