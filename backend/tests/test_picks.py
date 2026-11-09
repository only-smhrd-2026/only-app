"""사진 후보 조건과 가족방별 예약 선택을 실제 Postgres에서 검증한다."""

from datetime import datetime, time, timedelta

import pytest

from app.config import TZ, today_kst
from app.db import SessionLocal
from app.models import DailyPick, FamilyRoom, Photo
from app.services import picks, scheduler
from tests.conftest import add_photos, make_room, signup


@pytest.fixture
def room_photo(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    return room_id, add_photos(room_id, 1)[0]


@pytest.mark.parametrize("usable", [False, None, True])
def test_usable(room_photo, usable):
    room_id, photo_id = room_photo
    with SessionLocal() as db:
        db.get(Photo, photo_id).usable = usable
        db.commit()
        pick = picks.select_pick(db, room_id, today_kst())
        if usable is False:
            assert pick is None
        else:
            assert pick.photo_id == photo_id


@pytest.mark.parametrize("offset_us", [-1, 0, 1])
def test_upload_kst_midnight(room_photo, offset_us):
    room_id, photo_id = room_photo
    today = today_kst()
    with SessionLocal() as db:
        db.get(Photo, photo_id).uploaded_at = (
            datetime.combine(today, time.min, tzinfo=TZ) + timedelta(microseconds=offset_us)
        )
        db.commit()
        pick = picks.select_pick(db, room_id, today)
        if offset_us < 0:
            assert pick.photo_id == photo_id
        else:
            assert pick is None


@pytest.mark.parametrize("status", ["SKIPPED", "EXPIRED"])
def test_unfinished_photo_available_next_day(room_photo, status):
    room_id, photo_id = room_photo
    today = today_kst()
    with SessionLocal() as db:
        db.add(DailyPick(room_id=room_id, photo_id=photo_id, pick_date=today - timedelta(days=1), status=status))
        db.commit()
        assert picks.select_pick(db, room_id, today).photo_id == photo_id


@pytest.mark.parametrize("days_ago", [1, 13, 14, 15])
def test_completed_photo_excluded_for_14_days(room_photo, days_ago):
    room_id, photo_id = room_photo
    today = today_kst()
    with SessionLocal() as db:
        db.add(DailyPick(
            room_id=room_id, photo_id=photo_id,
            pick_date=today - timedelta(days=days_ago), status="COMPLETED",
        ))
        db.commit()
        pick = picks.select_pick(db, room_id, today)
        if days_ago <= 14:
            assert pick is None
        else:
            assert pick.photo_id == photo_id


def test_scheduler_respects_memory_time_and_existing_pick(client, monkeypatch):
    signup(client)
    room_ids = [make_room(client)["room_id"] for _ in range(3)]
    photos = [add_photos(room_id, 1)[0] for room_id in room_ids]
    today = today_kst()
    with SessionLocal() as db:
        for room_id, memory_time in zip(room_ids, [time(9, 30), time(11), time(9)]):
            db.get(FamilyRoom, room_id).memory_time = memory_time
        db.add(DailyPick(room_id=room_ids[2], photo_id=photos[2], pick_date=today, status="SKIPPED"))
        db.commit()
    monkeypatch.setattr(scheduler, "now_kst", lambda: datetime.combine(today, time(10), tzinfo=TZ))
    monkeypatch.setattr(scheduler, "today_kst", lambda: today)
    scheduler.select_daily_picks()
    scheduler.select_daily_picks()
    with SessionLocal() as db:
        assert picks.today_pick(db, room_ids[0], today).photo_id == photos[0]
        assert picks.today_pick(db, room_ids[1], today) is None
        assert picks.today_pick(db, room_ids[2], today).status == "SKIPPED"
