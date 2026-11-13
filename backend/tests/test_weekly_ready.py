"""새 주 집계와 가족별 알림이 함께 한 번만 저장되는지 확인한다."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import TZ, now_kst
from app.db import SessionLocal
from app.models import Notification, RoomMember, WeeklySummary
from app.routers import devices
from app.services import scheduler, weekly
from tests.conftest import make_room, signup

NOW = datetime(2026, 11, 15, 19, tzinfo=TZ)


def notices(db, room_id):
    return db.scalars(
        select(Notification).where(Notification.room_id == room_id, Notification.kind == "WEEKLY_READY")
    ).all()


def test_active_members_once_per_week(client):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    second = signup(client)
    third = signup(client)
    with SessionLocal() as db:
        db.add_all(
            [
                RoomMember(room_id=room_id, user_id=second["user_id"], relation_tag="GRANDCHILD"),
                RoomMember(room_id=room_id, user_id=third["user_id"], relation_tag="OTHER", removed_at=now_kst()),
            ]
        )
        db.commit()
        weekly.build(db, room_id, NOW)
        weekly.build(db, room_id, NOW)
        rows = notices(db, room_id)
        assert len(rows) == 2
        assert {n.target_user_id for n in rows} == {owner["user_id"], second["user_id"]}
        for notice in rows:
            assert notice.target_type == "FAMILY"
            assert notice.title == "순자 님의 이번 주 이야기가 도착했어요"
            assert notice.link_screen == "WEEKLY_001"
            assert notice.body is None
        weekly.build(db, room_id, NOW - timedelta(days=7))
        assert len(notices(db, room_id)) == 4


def test_scheduler_repeated(client, monkeypatch):
    signup(client)
    room_id = make_room(client)["room_id"]
    monkeypatch.setattr(scheduler, "now_kst", lambda: NOW)
    scheduler.weekly_summaries()
    scheduler.weekly_summaries()
    with SessionLocal() as db:
        assert len(notices(db, room_id)) == 1


def test_notification_failure_rolls_back_summary(client, monkeypatch):
    signup(client)
    room_id = make_room(client)["room_id"]
    original = devices.notify_family

    def fail_after_notice(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("테스트 실패")

    monkeypatch.setattr(weekly, "notify_family", fail_after_notice)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            weekly.build(db, room_id, NOW)
        db.rollback()
        assert db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id)) is None
        assert notices(db, room_id) == []
        monkeypatch.setattr(weekly, "notify_family", original)
        weekly.build(db, room_id, NOW)
        assert len(notices(db, room_id)) == 1
