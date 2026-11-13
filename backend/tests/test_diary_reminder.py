"""일기 알림의 한국 날짜·예약 시각·대상 조건과 하루 한 번 생성을 확인한다."""

import uuid
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.config import TZ, today_kst
from app.db import SessionLocal
from app.models import Diary, FamilyRoom, Notification
from app.services import scheduler
from tests.conftest import make_room, setup_elder, signup


def _at(monkeypatch, hour=19, minute=0):
    now = datetime.combine(today_kst(), time(hour, minute), tzinfo=TZ)
    monkeypatch.setattr(scheduler, "now_kst", lambda: now)
    return now


def _reminders(room_id):
    with SessionLocal() as db:
        return db.scalars(
            select(Notification).where(Notification.room_id == room_id, Notification.kind == "DIARY_REMINDER")
        ).all()


def test_time_and_repeated_run(client, monkeypatch):
    room_id = setup_elder(client)["room_id"]
    _at(monkeypatch, 18, 59)
    scheduler.diary_reminders()
    assert _reminders(room_id) == []
    now = _at(monkeypatch)
    scheduler.diary_reminders()
    first = _reminders(room_id)
    assert len(first) == 1
    assert first[0].target_type == "ELDER"
    assert first[0].target_user_id is None
    assert first[0].link_screen == "ELDER_DIARY_001"
    assert first[0].sent_at == now
    with SessionLocal() as db:
        room = db.get(FamilyRoom, room_id)
        assert first[0].title == f"{room.elder_name} {room.elder_honorific}, 오늘 일기를 써 볼까요?"
    scheduler.diary_reminders()
    assert [n.notification_id for n in _reminders(room_id)] == [first[0].notification_id]


@pytest.mark.parametrize(
    "author_type,status,yesterday,expected",
    [
        ("ELDER", "POSTED", False, 0),
        ("FAMILY", "POSTED", False, 1),
        ("ELDER", "POSTED", True, 1),
        ("ELDER", "DELETED", False, 1),
    ],
)
def test_diary_filters(client, monkeypatch, author_type, status, yesterday, expected):
    room_id = setup_elder(client)["room_id"]
    now = _at(monkeypatch)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        db.add(
            Diary(
                room_id=room_id,
                author_type=author_type,
                author_user_id=db.get(FamilyRoom, room_id).owner_user_id if author_type == "FAMILY" else None,
                body="테스트 일기",
                mood="SUNNY",
                illustration_type="NONE",
                request_id=uuid.uuid4(),
                status=status,
                posted_at=midnight - timedelta(seconds=1) if yesterday else midnight,
            )
        )
        db.commit()
    scheduler.diary_reminders()
    assert len(_reminders(room_id)) == expected


@pytest.mark.parametrize("condition", ["unconnected", "closed", "later"])
def test_ineligible_room(client, monkeypatch, condition):
    if condition == "unconnected":
        signup(client)
        room_id = make_room(client)["room_id"]
    else:
        room_id = setup_elder(client)["room_id"]
        with SessionLocal() as db:
            room = db.get(FamilyRoom, room_id)
            if condition == "closed":
                room.status = "CLOSED"
            else:
                room.diary_time = time(20, 0)
            db.commit()
    _at(monkeypatch)
    scheduler.diary_reminders()
    assert _reminders(room_id) == []


def test_previous_day_reminder_does_not_block(client, monkeypatch):
    room_id = setup_elder(client)["room_id"]
    now = _at(monkeypatch)
    with SessionLocal() as db:
        db.add(
            Notification(
                room_id=room_id,
                target_type="ELDER",
                kind="DIARY_REMINDER",
                title="테스트 알림",
                sent_at=now - timedelta(days=1),
            )
        )
        db.commit()
    scheduler.diary_reminders()
    scheduler.diary_reminders()
    assert len(_reminders(room_id)) == 2
