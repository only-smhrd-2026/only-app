"""11/16 기분 이름 바꾸기 (D75): 배포 서버용 ALTER 파일이 옛 날씨 값을 새 값으로 옮기고, 두 번 돌려도 되는지."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import ROOT
from app.db import SessionLocal, engine
from app.models import Diary, WeeklySummary
from tests.conftest import make_room, signup

MIGRATION = ROOT / "db" / "migrations" / "20261116_mood_faces.sql"
OLD_DIARY = (
    "INSERT INTO diaries (room_id, author_type, body, mood, illustration_type, request_id)"
    " VALUES (:r, 'ELDER', '일기', :m, 'NONE', :q)"
)
OLD_WEEK = (
    "INSERT INTO weekly_summaries (room_id, week_start, memory_days, diary_days, qa_list, recall_check, mood_trend,"
    " talk_volume, diaries, rule_check_passed, model_version) VALUES (:r, '2026-11-09', 0, 2, '[]', '{}',"
    """ '[{"date": "2026-11-09", "mood": "RAINY"}, {"date": "2026-11-10", "mood": null}]', '{}',"""
    """ '[{"diary_id": 1, "date": "2026-11-09", "mood": "MOON"}]', true, 'test')"""
)


def test_migration_moves_weather_moods(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("ALTER TABLE diaries DROP CONSTRAINT diaries_mood_check")  # 옛 서버 DB 흉내
        for mood in ("SUNNY", "CLOUDY", "RAINY", "MOON"):
            conn.execute(text(OLD_DIARY), {"r": room_id, "m": mood, "q": uuid.uuid4()})
        conn.execute(text(OLD_WEEK), {"r": room_id})
        conn.exec_driver_sql(MIGRATION.read_text("utf-8"))
        conn.exec_driver_sql(MIGRATION.read_text("utf-8"))  # 두 번 돌려도 된다
    with SessionLocal() as db:
        moods = db.scalars(select(Diary.mood).where(Diary.room_id == room_id).order_by(Diary.diary_id)).all()
        assert moods == ["GOOD", "SO_SO", "UPSET", "SO_SO"]  # 달은 뜻을 정한 적이 없어 '그저 그랬어요'로
        week = db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id))
        assert [d["mood"] for d in week.mood_trend] == ["UPSET", None]
        assert week.diaries[0]["mood"] == "SO_SO"
        db.add(
            Diary(
                room_id=room_id,
                author_type="ELDER",
                body="일기",
                mood="SUNNY",
                illustration_type="NONE",
                request_id=uuid.uuid4(),
            )
        )
        with pytest.raises(IntegrityError):  # 옛 값은 다시 못 들어온다
            db.commit()
