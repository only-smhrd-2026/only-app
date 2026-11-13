"""기록 없는 기간·기기 연결일·가족 알림의 중복 방지를 확인한다."""

import uuid
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.config import TZ, today_kst
from app.db import SessionLocal
from app.models import Diary, FamilyRoom, Notification, TalkSession
from app.services import scheduler
from tests.conftest import setup_elder


@pytest.fixture
def old_room(client, monkeypatch):
    room_id = setup_elder(client)["room_id"]
    now = datetime.combine(today_kst(), time(19), tzinfo=TZ)
    monkeypatch.setattr(scheduler, "now_kst", lambda: now)
    with SessionLocal() as db:
        db.get(FamilyRoom, room_id).device_connected_at = now - timedelta(days=3)
        db.commit()
    return room_id, now


def _alerts(room_id):
    with SessionLocal() as db:
        return db.scalars(
            select(Notification).where(Notification.room_id == room_id, Notification.kind == "NO_RECORD_2D")
        ).all()


def test_no_records_and_repeated_run(old_room):
    room_id, _ = old_room
    scheduler.no_record_alerts()
    first = _alerts(room_id)
    assert len(first) == 1
    assert first[0].target_type == "FAMILY"
    assert first[0].body == "전화 한 통 드려 보세요"
    assert first[0].link_screen == "HOME_001"
    with SessionLocal() as db:
        room = db.get(FamilyRoom, room_id)
        assert first[0].target_user_id == room.owner_user_id
        assert first[0].title == f"{room.elder_name} 님이 이틀째 기록이 없어요"
    scheduler.no_record_alerts()
    assert [n.notification_id for n in _alerts(room_id)] == [first[0].notification_id]


@pytest.mark.parametrize("condition", ["new", "boundary", "unconnected", "closed"])
def test_ineligible_room(old_room, condition):
    room_id, now = old_room
    with SessionLocal() as db:
        room = db.get(FamilyRoom, room_id)
        if condition == "new":
            room.device_connected_at = now
        elif condition == "boundary":
            room.device_connected_at = now.replace(hour=0) - timedelta(days=1)
        elif condition == "unconnected":
            room.device_token_hash = None
        else:
            room.status = "CLOSED"
        db.commit()
    scheduler.no_record_alerts()
    assert _alerts(room_id) == []


@pytest.mark.parametrize("when,expected", [("yesterday", 0), ("older", 1), ("unfinished", 1), ("boundary", 0)])
def test_finished_talk_window(old_room, when, expected):
    room_id, now = old_room
    since = now.replace(hour=0) - timedelta(days=1)
    ended_at = {
        "yesterday": now - timedelta(days=1),
        "older": since - timedelta(microseconds=1),
        "unfinished": None,
        "boundary": since,
    }[when]
    with SessionLocal() as db:
        db.add(
            TalkSession(
                session_id=uuid.uuid4(),
                room_id=room_id,
                kind="MEMORY",
                input_mode="VOICE",
                started_at=(ended_at or now) - timedelta(minutes=5),
                ended_at=ended_at,
                end_reason="COMPLETED" if ended_at else None,
            )
        )
        db.commit()
    scheduler.no_record_alerts()
    assert len(_alerts(room_id)) == expected


@pytest.mark.parametrize(
    "author_type,status,expected", [("ELDER", "POSTED", 0), ("FAMILY", "POSTED", 1), ("ELDER", "DELETED", 1)]
)
def test_diary_filters(old_room, author_type, status, expected):
    room_id, now = old_room
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
                posted_at=now,
            )
        )
        db.commit()
    scheduler.no_record_alerts()
    assert len(_alerts(room_id)) == expected


def test_previous_alert_does_not_block_today(old_room):
    room_id, now = old_room
    with SessionLocal() as db:
        db.add(
            Notification(
                room_id=room_id,
                target_type="FAMILY",
                kind="NO_RECORD_2D",
                title="테스트 알림",
                sent_at=now.replace(hour=0) - timedelta(microseconds=1),
            )
        )
        db.commit()
    scheduler.no_record_alerts()
    scheduler.no_record_alerts()
    assert len(_alerts(room_id)) == 2
