"""시연 자료의 날짜·기분·멱등성과 기존 자료 보존을 확인한다."""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.config import TZ
from app.db import SessionLocal
from app.models import Diary, FamilyRoom, MoodCheck, TalkSession, WeeklySummary
from scripts.demo_data import fill
from tests.conftest import make_room, signup

NOW = datetime(2026, 11, 16, 9, tzinfo=TZ)


def test_fill_preserves_existing_and_is_repeatable(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        assert fill(db, room_id, NOW) == {"sessions": 5, "diaries": 4, "mood_checks": 1, "weekly_summaries": 1}
        talks = db.scalars(select(TalkSession).where(TalkSession.room_id == room_id)).all()
        assert len({s.started_at.astimezone(TZ).date() for s in talks}) == 5
        assert sum(s.emotion_flag == "LOW" for s in talks) == 1
        assert all(set(t) == {"turn_no", "speaker", "text", "created_at"} for s in talks for t in s.turns)
        diaries = db.scalars(select(Diary).where(Diary.room_id == room_id)).all()
        assert {d.mood for d in diaries} == {"GOOD", "SO_SO", "UPSET", "LONELY"}
        diaries[0].body = "기존에 수정한 글은 보존"
        db.commit()
        assert fill(db, room_id, NOW) == dict.fromkeys(("sessions", "diaries", "mood_checks", "weekly_summaries"), 0)
        db.refresh(diaries[0])
        assert diaries[0].body == "기존에 수정한 글은 보존"
        check = db.scalar(select(MoodCheck).where(MoodCheck.room_id == room_id))
        assert check.check_date.isoformat() == "2026-11-06"
        summary = db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id))
        assert summary.week_start.isoformat() == "2026-11-09"
        assert summary.memory_days == 5
        assert summary.diary_days == 4


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
