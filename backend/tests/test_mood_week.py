"""마음 카드의 날짜 경계·활동 집계·최신 기분·가족방 접근 범위를 확인한다."""

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import TZ
from app.db import SessionLocal
from app.models import Diary, FamilyRoom, MoodCheck, RoomMember, TalkSession
from app.routers import mood
from tests.conftest import make_room, signup


@pytest.fixture
def context(client, monkeypatch):
    today = date(2026, 11, 13)
    monkeypatch.setattr(mood, "today_kst", lambda: today)
    user = signup(client)
    room_id = make_room(client)["room_id"]
    return room_id, datetime.combine(today, time.min, tzinfo=TZ), user["user_id"]


def _talk(room_id, at, emotion="NONE", kind="MEMORY", private=False, speaker="ELDER"):
    with SessionLocal() as db:
        db.add(
            TalkSession(
                session_id=uuid.uuid4(),
                room_id=room_id,
                kind=kind,
                input_mode="VOICE",
                started_at=at,
                emotion_flag=emotion,
                private_flag=private,
                turns=[{"speaker": speaker, "text": "비공개 테스트 대화"}],
            )
        )
        db.commit()


def _diary(room_id, at, mood_value, author_type="ELDER", status="POSTED"):
    with SessionLocal() as db:
        db.add(
            Diary(
                room_id=room_id,
                author_type=author_type,
                author_user_id=db.get(FamilyRoom, room_id).owner_user_id if author_type == "FAMILY" else None,
                body="비공개 테스트 일기",
                mood=mood_value,
                illustration_type="NONE",
                request_id=uuid.uuid4(),
                posted_at=at,
                status=status,
            )
        )
        db.commit()


def _get(client, room_id):
    response = client.get(f"/api/rooms/{room_id}/mood-week")
    assert response.status_code == 200, response.text
    assert "비공개 테스트" not in response.text
    return response.json()


def test_empty_week(client, context):
    room_id, midnight, _ = context
    result = _get(client, room_id)
    assert result == {
        "days": [
            {
                "date": (midnight.date() - timedelta(days=offset)).isoformat(),
                "talked": False,
                "diary_mood": None,
                "low": False,
            }
            for offset in range(6, -1, -1)
        ],
        "talked_days": 0,
        "low_days": 0,
        "last_check": None,
    }


def test_talk_days_low_and_window(client, context):
    room_id, midnight, _ = context
    _talk(room_id, midnight)
    _talk(room_id, midnight - timedelta(days=2), "SAD", kind="ALBUM")
    _talk(room_id, midnight - timedelta(days=2) + timedelta(hours=1), kind="DIARY")
    _talk(room_id, midnight - timedelta(days=7), "SAD")
    other_room = make_room(client)["room_id"]
    _talk(other_room, midnight, "SAD")
    result = _get(client, room_id)
    assert result["days"][-1] == {"date": midnight.date().isoformat(), "talked": True, "diary_mood": None, "low": False}
    assert result["days"][-3]["talked"] is True
    assert result["days"][-3]["low"] is True
    assert result["talked_days"] == 2
    assert result["low_days"] == 1


def test_latest_elder_mood_only(client, context):
    room_id, midnight, _ = context
    yesterday = midnight - timedelta(days=1)
    _diary(room_id, yesterday + timedelta(hours=9), "RAINY")
    _diary(room_id, yesterday + timedelta(hours=10), "SUNNY")
    _diary(room_id, yesterday + timedelta(hours=11), "MOON", author_type="FAMILY")
    _diary(room_id, yesterday + timedelta(hours=12), "CLOUDY", status="DELETED")
    _diary(room_id, midnight - timedelta(days=7), "RAINY")
    result = _get(client, room_id)
    assert result["days"][-2]["diary_mood"] == "SUNNY"
    assert sum(day["diary_mood"] is not None for day in result["days"]) == 1
    assert result["talked_days"] == 0


def test_same_timestamp_uses_later_diary_id(client, context):
    room_id, midnight, _ = context
    _diary(room_id, midnight, "RAINY")
    _diary(room_id, midnight, "SUNNY")
    assert _get(client, room_id)["days"][-1]["diary_mood"] == "SUNNY"


def test_korean_midnight_and_first_day_boundary(client, context):
    room_id, midnight, _ = context
    # UTC로 넣어도 한국 날짜로 나누며, 범위 첫날의 0시를 포함한다.
    _talk(room_id, midnight.astimezone(timezone.utc))
    _talk(room_id, (midnight - timedelta(microseconds=1)).astimezone(timezone.utc), "SAD")
    first = midnight - timedelta(days=6)
    _talk(room_id, first)
    _talk(room_id, first - timedelta(microseconds=1), "SAD")
    _diary(room_id, midnight.astimezone(timezone.utc), "SUNNY")
    _diary(room_id, (midnight - timedelta(microseconds=1)).astimezone(timezone.utc), "RAINY")
    result = _get(client, room_id)
    assert result["days"][-1]["talked"] is True
    assert result["days"][-1]["low"] is False
    assert result["days"][-1]["diary_mood"] == "SUNNY"
    assert result["days"][-2]["low"] is True
    assert result["days"][-2]["diary_mood"] == "RAINY"
    assert result["days"][0]["talked"] is True
    assert result["days"][0]["low"] is False
    assert result["talked_days"] == 3
    assert result["low_days"] == 1


def test_auth_and_other_room(client, context):
    room_id, _, _ = context
    signup(client)
    for hidden in (room_id, 999999):
        response = client.get(f"/api/rooms/{hidden}/mood-week")
        assert response.status_code == 404
        assert response.json()["code"] == "ROOM_NOT_FOUND"
    client.cookies.clear()
    response = client.get(f"/api/rooms/{room_id}/mood-week")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_removed_member(client, context):
    room_id, midnight, user_id = context
    with SessionLocal() as db:
        member = db.scalar(select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == user_id))
        member.removed_at = midnight
        db.commit()
    response = client.get(f"/api/rooms/{room_id}/mood-week")
    assert response.status_code == 404
    assert response.json()["code"] == "ROOM_NOT_FOUND"


def test_low_and_risk_count(client, context):
    room_id, midnight, _ = context
    _talk(room_id, midnight, "LOW")
    _talk(room_id, midnight - timedelta(days=1), "RISK")
    _talk(room_id, midnight - timedelta(days=2), "NONE")
    result = _get(client, room_id)
    assert result["days"][-1]["low"] is True
    assert result["days"][-2]["low"] is True
    assert result["days"][-3]["low"] is False
    assert result["low_days"] == 2


def test_talked_needs_elder_words_and_private_low_is_left_out(client, context):
    room_id, midnight, _ = context
    _talk(room_id, midnight, speaker="AI")  # 열기만 한 대화 — 이야기한 날이 아니다
    _talk(room_id, midnight - timedelta(days=1), "LOW", private=True)  # 비밀 부탁 — 이야기한 날로만 센다
    _talk(room_id, midnight - timedelta(days=2), "RISK", private=True)  # 위급은 비밀 부탁이어도 보인다 (D55 ③)
    result = _get(client, room_id)
    assert [(day["talked"], day["low"]) for day in result["days"][-3:]] == [(True, True), (True, False), (False, False)]
    assert (result["talked_days"], result["low_days"]) == (2, 1)


def test_last_check_latest_date_and_level_only(client, context):
    room_id, _, _ = context
    other_room = make_room(client)["room_id"]
    with SessionLocal() as db:
        db.add_all(
            [
                MoodCheck(room_id=room_id, check_date=date(2026, 10, 20), answers=[0] * 8, total=0, level="USUAL"),
                MoodCheck(room_id=room_id, check_date=date(2026, 11, 3), answers=[1] * 8, total=8, level="DOWN"),
                MoodCheck(room_id=other_room, check_date=date(2026, 11, 12), answers=[2] * 8, total=16, level="HARD"),
            ]
        )
        db.commit()
    response = client.get(f"/api/rooms/{room_id}/mood-week")
    assert response.status_code == 200
    assert response.json()["last_check"] == {"check_date": "2026-11-03", "level": "DOWN"}
    assert "total" not in response.text
    assert "answers" not in response.text
