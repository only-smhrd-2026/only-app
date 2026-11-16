"""시연 자료의 날짜·기분·멱등성과 기존 자료 보존을 확인한다."""

import sys
from datetime import datetime

import pytest
from sqlalchemy import select

from app.config import TZ
from app.db import SessionLocal
from app.models import Diary, FamilyRoom, MoodCheck, Notification, TalkSession, WeeklySummary
from scripts import demo_data
from scripts.demo_data import fill
from tests.conftest import make_room, signup

NOW = datetime(2026, 11, 16, 9, tzinfo=TZ)


def test_fill_preserves_existing_and_is_repeatable(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        first = fill(db, room_id, NOW)
        assert first == {
            "sessions": 5,
            "diaries": 6,
            "mood_checks": 1,
            "weekly_summaries": 1,
            "hearts": 1,
            "notifications": 3,
        }
        talks = db.scalars(select(TalkSession).where(TalkSession.room_id == room_id)).all()
        assert len({s.started_at.astimezone(TZ).date() for s in talks}) == 5
        assert sum(s.emotion_flag == "LOW" for s in talks) == 1
        assert all({"turn_no", "speaker", "text", "created_at"} <= set(t) for s in talks for t in s.turns)
        assert all(t["reply_to_turn_no"] == 1 for s in talks for t in s.turns if t["speaker"] == "ELDER")
        diaries = db.scalars(select(Diary).where(Diary.room_id == room_id)).all()
        assert {d.mood for d in diaries} == {"GOOD", "SO_SO", "UPSET", "LONELY"}
        diaries[0].body = "기존에 수정한 글은 보존"
        db.commit()
        assert fill(db, room_id, NOW) == dict.fromkeys(first, 0)
        db.refresh(diaries[0])
        assert diaries[0].body == "기존에 수정한 글은 보존"
        check = db.scalar(select(MoodCheck).where(MoodCheck.room_id == room_id))
        assert check.check_date.isoformat() == "2026-11-06"
        summary = db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id))
        assert summary.week_start.isoformat() == "2026-11-09"
        assert summary.memory_days == 5
        assert summary.diary_days == 4
        assert 1 <= len(summary.qa_list) <= 4
        family = [d for d in diaries if d.author_type == "FAMILY"]
        assert len(family) == 2
        assert all(
            d.author_user_id == db.get(FamilyRoom, room_id).owner_user_id and d.elder_read_at is None for d in family
        )
        hearts = [r for d in diaries for r in d.reactions]
        assert len(hearts) == 1 and hearts[0]["kind"] == "HEART"
        notices = db.scalars(
            select(Notification).where(
                Notification.room_id == room_id, Notification.kind.in_(["DIARY_POSTED", "DEVICE_CONNECTED"])
            )
        ).all()
        assert len(notices) == 3 and all(n.sent_at == NOW for n in notices)


def test_missing_or_closed_room_does_nothing(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        db.get(FamilyRoom, room_id).status = "CLOSED"
        db.commit()
        for invalid in (room_id, -1):
            with pytest.raises(ValueError, match="가족방이 없거나 닫혀"):
                fill(db, invalid, NOW)
        assert db.scalar(select(TalkSession).where(TalkSession.room_id == room_id)) is None
        assert db.scalar(select(Diary).where(Diary.room_id == room_id)) is None
        assert db.scalar(select(MoodCheck).where(MoodCheck.room_id == room_id)) is None


def test_deploy_requires_force_before_database_access(monkeypatch):
    monkeypatch.setattr(demo_data.settings, "APP_ENV", "deploy")
    monkeypatch.setattr(sys, "argv", ["demo_data", "--room-id", "1"])
    monkeypatch.setattr(demo_data, "SessionLocal", lambda: pytest.fail("배포 보호 전에 DB를 열면 안 됩니다"))
    with pytest.raises(SystemExit) as exc:
        demo_data.main()
    assert exc.value.code == 1


def test_cli_force_outputs_counts_without_personal_text(client, monkeypatch, capsys):
    signup(client)
    room = make_room(client)["room_id"]
    monkeypatch.setattr(demo_data.settings, "APP_ENV", "deploy")
    monkeypatch.setattr(demo_data, "now_kst", lambda: NOW)
    monkeypatch.setattr(sys, "argv", ["demo_data", "--room-id", str(room), "--force"])
    demo_data.main()
    output = capsys.readouterr().out
    assert "notifications: 3" in output
    assert "순자" not in output and "마당" not in output and "산책" not in output
    demo_data.main()
    output = capsys.readouterr().out
    assert "sessions: 0" in output and "diaries: 0" in output and "notifications: 0" in output
