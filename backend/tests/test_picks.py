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
        db.get(Photo, photo_id).uploaded_at = datetime.combine(today, time.min, tzinfo=TZ) + timedelta(
            microseconds=offset_us
        )
        db.commit()
        pick = picks.select_pick(db, room_id, today)
        if offset_us < 0:
            assert pick.photo_id == photo_id
        else:
            assert pick is None


@pytest.mark.parametrize("status", ["SKIPPED", "EXPIRED", "PENDING"])
def test_unfinished_photo_available_next_day(room_photo, status):
    room_id, photo_id = room_photo
    today = today_kst()
    with SessionLocal() as db:
        db.add(DailyPick(room_id=room_id, photo_id=photo_id, pick_date=today - timedelta(days=1), status=status))
        db.commit()
        assert picks.select_pick(db, room_id, today).photo_id == photo_id


def _completed(db, room_id: int, photo_id: int, days_ago: int) -> None:
    db.add(
        DailyPick(
            room_id=room_id, photo_id=photo_id, pick_date=today_kst() - timedelta(days=days_ago), status="COMPLETED"
        )
    )


@pytest.mark.parametrize("days_ago", [1, 13, 14, 15])
def test_completed_photo_excluded_for_14_days(client, monkeypatch, days_ago):
    """다른 후보가 있으면 14일 안에 이야기한 사진(A)은 빼고 고른다. 15일째부터 A 도 다시 후보."""
    signup(client)
    room_id = make_room(client)["room_id"]
    photo_a, photo_b = add_photos(room_id, 2)
    monkeypatch.setattr(picks.random, "choice", lambda seq: photo_a if photo_a in seq else seq[0])
    with SessionLocal() as db:
        _completed(db, room_id, photo_a, days_ago)
        db.commit()
        pick = picks.select_pick(db, room_id, today_kst())
        assert pick.photo_id == (photo_b if days_ago <= 14 else photo_a)


def test_all_recently_completed_repeats_oldest(client):
    """사진이 적은 방이 14일 안에 다 이야기했으면 비우지 않고 가장 오래전에 이야기한 사진부터 다시 (D44)."""
    signup(client)
    room_id = make_room(client)["room_id"]
    photo_a, photo_b = add_photos(room_id, 2)
    with SessionLocal() as db:
        _completed(db, room_id, photo_a, 3)
        _completed(db, room_id, photo_b, 1)
        db.commit()
        assert picks.select_pick(db, room_id, today_kst()).photo_id == photo_a


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


def _job_at_ten(monkeypatch, today):
    monkeypatch.setattr(scheduler, "now_kst", lambda: datetime.combine(today, time(10), tzinfo=TZ))
    monkeypatch.setattr(scheduler, "today_kst", lambda: today)


def test_scheduler_second_run_keeps_first_pick(client, monkeypatch):
    """두 번째 실행이 이미 고른 사진을 바꾸지 않는다 — 다른 사진을 고르도록 바꿔 둬도 그대로."""
    signup(client)
    room_id = make_room(client)["room_id"]
    first, second, _ = add_photos(room_id, 3)
    today = today_kst()
    _job_at_ten(monkeypatch, today)
    monkeypatch.setattr(picks.random, "choice", lambda seq: first if first in seq else seq[0])
    scheduler.select_daily_picks()
    with SessionLocal() as db:
        before = picks.today_pick(db, room_id, today)
    monkeypatch.setattr(picks.random, "choice", lambda seq: second if second in seq else seq[0])
    scheduler.select_daily_picks()
    with SessionLocal() as db:
        after = picks.today_pick(db, room_id, today)
    assert (after.pick_id, after.photo_id) == (before.pick_id, first)


def test_scheduler_skips_closed_room_and_survives_room_error(client, monkeypatch):
    """닫힌(CLOSED) 방은 고르지 않고, 한 방에서 오류가 나도 다른 방은 고른다."""
    signup(client)
    closed, broken, ok = (make_room(client)["room_id"] for _ in range(3))
    for room_id in (closed, broken, ok):
        add_photos(room_id, 1)
    with SessionLocal() as db:
        db.get(FamilyRoom, closed).status = "CLOSED"
        db.commit()
    today = today_kst()
    _job_at_ten(monkeypatch, today)
    real = picks.select_pick

    def flaky(db, room_id, day):
        if room_id == broken:
            raise RuntimeError("boom")
        return real(db, room_id, day)

    monkeypatch.setattr(picks, "select_pick", flaky)
    scheduler.select_daily_picks()  # 예외가 밖으로 나오지 않는다
    with SessionLocal() as db:
        assert picks.today_pick(db, closed, today) is None
        assert picks.today_pick(db, broken, today) is None
        assert picks.today_pick(db, ok, today) is not None
