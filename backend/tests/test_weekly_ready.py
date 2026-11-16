"""새 주 집계와 가족별 알림이 함께 한 번만 저장되는지 확인한다."""

from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import TZ, now_kst
from app.db import SessionLocal
from app.models import Notification, RoomMember, WeeklySummary
from app.routers import devices
from app.services import scheduler
from tests.conftest import make_room, signup
from tests.test_weekly import _talk

NOW = datetime(2026, 11, 15, 19, tzinfo=TZ)


def notices(db, room_id):
    return db.scalars(
        select(Notification).where(Notification.room_id == room_id, Notification.kind == "WEEKLY_READY")
    ).all()


def test_active_members_once_per_week(client, monkeypatch):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    second = signup(client)
    third = signup(client)
    with SessionLocal() as db:
        _talk(db, room_id, NOW - timedelta(days=1), texts=("기록",))
        _talk(db, room_id, NOW - timedelta(days=8), texts=("기록",))
        db.add_all(
            [
                RoomMember(room_id=room_id, user_id=second["user_id"], relation_tag="GRANDCHILD"),
                RoomMember(room_id=room_id, user_id=third["user_id"], relation_tag="OTHER", removed_at=now_kst()),
            ]
        )
        db.commit()
    monkeypatch.setattr(scheduler, "now_kst", lambda: NOW)
    scheduler.weekly_summaries()
    scheduler.weekly_summaries()
    with SessionLocal() as db:
        rows = notices(db, room_id)
        assert len(rows) == 2
        assert {n.target_user_id for n in rows} == {owner["user_id"], second["user_id"]}
        for notice in rows:
            assert notice.target_type == "FAMILY"
            assert notice.title == "순자 님의 이번 주 이야기가 도착했어요"
            assert notice.link_screen == "WEEKLY_001"
            assert notice.body is None
    monkeypatch.setattr(scheduler, "now_kst", lambda: NOW - timedelta(days=7))
    scheduler.weekly_summaries()
    with SessionLocal() as db:
        assert len(notices(db, room_id)) == 4


def test_scheduler_repeated(client, monkeypatch):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        _talk(db, room_id, NOW - timedelta(days=1), texts=("기록",))
        db.commit()
    monkeypatch.setattr(scheduler, "now_kst", lambda: NOW)
    scheduler.weekly_summaries()
    scheduler.weekly_summaries()
    with SessionLocal() as db:
        assert len(notices(db, room_id)) == 1


def test_notification_failure_is_retried_without_duplicates(client, monkeypatch):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        _talk(db, room_id, NOW - timedelta(days=1), texts=("기록",))
        db.commit()
    original = devices.notify_family

    def fail_after_notice(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("테스트 실패")

    monkeypatch.setattr(scheduler, "notify_family", fail_after_notice)
    monkeypatch.setattr(scheduler, "now_kst", lambda: NOW)
    scheduler.weekly_summaries()
    with SessionLocal() as db:
        row = db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id))
        assert row is not None and row.published_at is None
        assert notices(db, room_id) == []
    monkeypatch.setattr(scheduler, "notify_family", original)
    scheduler.weekly_summaries()
    scheduler.weekly_summaries()
    with SessionLocal() as db:
        assert len(notices(db, room_id)) == 1
        assert db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id)).published_at == NOW


def test_summary_runs_before_notice_and_failure_still_notifies(client, monkeypatch, caplog):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        _talk(db, room_id, NOW - timedelta(days=1), texts=("기록",))
        db.commit()
    calls = []

    def fail_summary(db, rid, week):
        if rid == room_id:
            calls.append("summary")
            raise RuntimeError("비밀 본문")

    def notify(db, rid, *args, **kwargs):
        if rid == room_id:
            assert calls == ["summary"]
            calls.append("notice")
        return devices.notify_family(db, rid, *args, **kwargs)

    monkeypatch.setattr(scheduler, "now_kst", lambda: NOW)
    monkeypatch.setattr(scheduler, "summarize", fail_summary)
    monkeypatch.setattr(scheduler, "notify_family", notify)
    scheduler.weekly_summaries()
    assert calls == ["summary", "notice"]
    assert "비밀 본문" not in caplog.text
