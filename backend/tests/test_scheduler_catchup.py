"""기동 보정의 시각 경계·실패 격리와 빈 주 알림을 확인한다."""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.config import TZ
from app.db import SessionLocal
from app.models import Notification, WeeklySummary
from app.services import scheduler, weekly
from tests.conftest import make_room, signup


@pytest.mark.parametrize("hour,count", [(18, 1), (19, 3), (23, 3)])
def test_catch_up_hours_and_failure_isolation(monkeypatch, caplog, hour, count):
    called = []

    def weekly_summaries():
        called.append("weekly")
        raise RuntimeError("로그에 남기지 않을 글")

    monkeypatch.setattr(scheduler, "now_kst", lambda: datetime(2026, 11, 16, hour, tzinfo=TZ))
    monkeypatch.setattr(scheduler, "weekly_summaries", weekly_summaries)
    monkeypatch.setattr(scheduler, "diary_reminders", lambda: called.append("diary"))
    monkeypatch.setattr(scheduler, "no_record_alerts", lambda: called.append("no_record"))
    scheduler.catch_up()
    assert called == ["weekly", "diary", "no_record"][:count]
    assert "error=RuntimeError" in caplog.text
    assert "로그에 남기지 않을 글" not in caplog.text


def test_empty_week_has_summary_without_notification(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        weekly.build(db, room_id, datetime(2026, 11, 16, 9, tzinfo=TZ))
        assert db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id)) is not None
        assert db.scalar(select(Notification).where(Notification.room_id == room_id)) is None
