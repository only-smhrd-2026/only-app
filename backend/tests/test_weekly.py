"""주간 집계 창·숫자·멱등 저장·조회 권한과 예약 작업의 실패 격리를 확인한다."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import TZ
from app.db import SessionLocal
from app.models import Diary, FamilyRoom, Notification, Photo, TalkSession, WeeklySummary
from app.services import scheduler, weekly
from tests.conftest import add_photos, make_room, signup

NOW = datetime(2026, 11, 15, 19, tzinfo=TZ)


def _at(day, hour=10, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


def _talk(db, room_id, at, kind="MEMORY", texts=(), private=False):
    db.add(
        TalkSession(
            session_id=uuid.uuid4(),
            room_id=room_id,
            kind=kind,
            input_mode="VOICE",
            started_at=at,
            private_flag=private,
            turns=[{"turn_no": i, "speaker": "ELDER", "text": text} for i, text in enumerate(texts, 1)]
            + [{"speaker": "AI", "text": "이 말은 세지 않아요"}],
        )
    )


def _diary(db, room_id, at, mood="SUNNY", author_type="ELDER", status="POSTED", **picture):
    diary = Diary(
        room_id=room_id,
        author_type=author_type,
        author_user_id=db.get(FamilyRoom, room_id).owner_user_id if author_type == "FAMILY" else None,
        body="저장하면 안 되는 테스트 본문",
        mood=mood,
        **({"illustration_type": "NONE"} | picture),
        request_id=uuid.uuid4(),
        posted_at=at,
        status=status,
    )
    db.add(diary)
    db.flush()
    return diary.diary_id


def _rows(room_id):
    with SessionLocal() as db:
        return db.scalars(
            select(WeeklySummary).where(WeeklySummary.room_id == room_id).order_by(WeeklySummary.week_start)
        ).all()


@pytest.mark.parametrize(
    "now,week_start",
    [
        (NOW, date(2026, 11, 9)),
        (NOW - timedelta(minutes=1), date(2026, 11, 2)),
        (_at(18), date(2026, 11, 9)),
        (NOW.astimezone(timezone.utc), date(2026, 11, 9)),
    ],
)
def test_window(now, week_start):
    start, end, actual_week = weekly.window(now)
    assert actual_week == week_start
    assert start == datetime.combine(week_start, NOW.timetz()) - timedelta(days=1)
    assert end == start + timedelta(days=7)


def test_build_and_repeated_run(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        _talk(db, room_id, _at(10), texts=("김장하던 날이 생각나요", "네"))
        _talk(db, room_id, _at(11), "ALBUM", ("마당에서 찍었어요",))
        _talk(db, room_id, _at(11, 20), "DIARY", ("경로당에 다녀왔어요",))
        _talk(db, room_id, _at(8, 18, 59), texts=("범위 밖",))
        _talk(db, room_id, NOW, texts=("범위 밖",))
        diary_id = _diary(db, room_id, _at(11, 20, 5))
        _diary(db, room_id, NOW, "RAINY")
        _diary(db, room_id, _at(12), "MOON", "FAMILY")
        _diary(db, room_id, _at(13), "RAINY", status="DELETED")
        db.commit()
        weekly.build(db, room_id, NOW)
    row = _rows(room_id)[0]
    assert row.week_start == date(2026, 11, 9)
    assert (row.memory_days, row.diary_days) == (2, 1)
    assert row.talk_volume == {"words": 8, "turns": 4, "avg_words": 2.0}
    assert row.mood_trend == [
        {"date": date(2026, 11, day).isoformat(), "mood": "SUNNY" if day == 11 else None} for day in range(9, 16)
    ]
    assert row.diaries == [{"diary_id": diary_id, "date": "2026-11-11", "mood": "SUNNY"}]
    assert row.qa_list == []
    assert row.recall_check == {}
    assert row.notes is None
    assert row.baseline_talk is None
    assert row.published_at is None
    assert row.rule_check_passed is False
    assert row.model_version == "none"
    with SessionLocal() as db:
        _talk(db, room_id, _at(12), texts=("나중에 추가한 말",))
        db.commit()
        weekly.build(db, room_id, NOW)
    assert len(_rows(room_id)) == 1
    assert _rows(room_id)[0].talk_volume == row.talk_volume


def test_eight_dates_latest_mood_and_empty_week(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        for offset in range(8):
            at = _at(8, 19) + timedelta(days=offset)
            if offset == 7:
                at -= timedelta(hours=1)
            _talk(db, room_id, at, texts=("네",))
            _diary(db, room_id, at, "RAINY")
        _diary(db, room_id, _at(11, 22), "SUNNY")
        db.commit()
        weekly.build(db, room_id, NOW)
        weekly.build(db, room_id, NOW - timedelta(days=7))
    empty, full = _rows(room_id)
    assert (full.memory_days, full.diary_days) == (7, 7)
    assert full.mood_trend[2]["mood"] == "SUNNY"
    assert len(full.diaries) == 9
    assert empty.talk_volume == {"words": 0, "turns": 0, "avg_words": 0}
    assert (empty.memory_days, empty.diary_days) == (0, 0)


def test_only_elder_words_count_and_private_talk_is_left_out(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    with SessionLocal() as db:
        _talk(db, room_id, _at(10))  # 열기만 한 대화 — 이야기한 날이 아니다
        _talk(db, room_id, _at(11), texts=("애들한테는 말하지 마",), private=True)  # 이야기한 날로만, 말 수에서는 뺀다
        _talk(db, room_id, _at(12), texts=("네",))
        db.add(  # 키가 빠진 칸이 있어도 그 방 집계가 실패하지 않는다
            TalkSession(
                session_id=uuid.uuid4(),
                room_id=room_id,
                kind="MEMORY",
                input_mode="VOICE",
                started_at=_at(12, 11),
                turns=[{"speaker": "ELDER", "text": "그럼요 좋지요"}, {"text": "키가 빠진 칸"}, {"speaker": "ELDER"}],
            )
        )
        db.commit()
        weekly.build(db, room_id, NOW)
    row = _rows(room_id)[0]
    assert row.memory_days == 2
    assert row.talk_volume == {"words": 3, "turns": 3, "avg_words": 1.0}


def test_diary_pictures_like_home_cards(client):
    """일기 사진 줄: 사진·그림일기는 가족 홈 카드와 같은 주소, 그림 없는 일기·나중에 지운 일기는 None (목업 ⑤)"""
    signup(client)
    room_id = make_room(client)["room_id"]
    photo_id = add_photos(room_id, 1)[0]
    with SessionLocal() as db:
        photo = _diary(db, room_id, _at(10), illustration_type="PHOTO", photo_id=photo_id)
        drawn = _diary(db, room_id, _at(11), illustration_type="AI_DRAWING", illustration_key="draw/1.png")
        plain = _diary(db, room_id, _at(12))
        gone = _diary(db, room_id, _at(13))
        db.commit()
        weekly.build(db, room_id, NOW)
        db.get(Diary, gone).status = "DELETED"
        db.commit()
        key = db.get(Photo, photo_id).object_key
    urls = {d["diary_id"]: d["illustration_url"] for d in client.get(f"/api/rooms/{room_id}/weekly").json()["diaries"]}
    assert urls == {photo: f"/api/media/{key}", drawn: "/api/media/draw/1.png", plain: None, gone: None}


def test_get_latest_specific_and_permissions(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    path = f"/api/rooms/{room_id}/weekly"
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["code"] == "WEEKLY_NOT_FOUND"
    with SessionLocal() as db:
        weekly.build(db, room_id, NOW)
        weekly.build(db, room_id, NOW - timedelta(days=7))
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["week_start"] == "2026-11-09"
    assert set(response.json()) == {
        "week_start",
        "prev_week_start",
        "next_week_start",
        "memory_days",
        "diary_days",
        "qa_list",
        "recall_check",
        "mood_trend",
        "talk_volume",
        "diaries",
        "notes",
    }
    assert (response.json()["prev_week_start"], response.json()["next_week_start"]) == ("2026-11-02", None)
    older = client.get(path + "?week_start=2026-11-02").json()
    assert (older["week_start"], older["prev_week_start"]) == ("2026-11-02", None)
    assert older["next_week_start"] == "2026-11-09"
    response = client.get(path + "?week_start=2026-10-26")
    assert response.status_code == 404
    assert response.json()["code"] == "WEEKLY_NOT_FOUND"
    signup(client)
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["code"] == "ROOM_NOT_FOUND"
    client.cookies.clear()
    assert client.get(path).status_code == 401


def test_scheduler_repeated_and_closed_room(client, monkeypatch):
    signup(client)
    room_id = make_room(client)["room_id"]
    closed = make_room(client)["room_id"]
    with SessionLocal() as db:
        db.get(FamilyRoom, closed).status = "CLOSED"
        db.commit()
    monkeypatch.setattr(scheduler, "now_kst", lambda: NOW)
    scheduler.weekly_summaries()
    scheduler.weekly_summaries()
    assert len(_rows(room_id)) == 1
    assert _rows(closed) == []
    with SessionLocal() as db:
        assert (
            len(
                db.scalars(
                    select(Notification).where(Notification.room_id == room_id, Notification.kind == "WEEKLY_READY")
                ).all()
            )
            == 1
        )


def test_scheduler_rolls_back_and_continues(client, monkeypatch, caplog):
    signup(client)
    failed = make_room(client)["room_id"]
    next_room = make_room(client)["room_id"]
    original = weekly.build

    def build(db, room_id, now):
        if room_id == failed:
            db.get(FamilyRoom, room_id).status = "CLOSED"
            db.flush()
            raise RuntimeError("로그에 남기면 안 되는 내용")
        original(db, room_id, now)

    monkeypatch.setattr(weekly, "build", build)
    monkeypatch.setattr(scheduler, "now_kst", lambda: NOW)
    scheduler.weekly_summaries()
    assert _rows(failed) == []
    assert len(_rows(next_room)) == 1
    with SessionLocal() as db:
        assert db.get(FamilyRoom, failed).status == "ACTIVE"
    assert "error=RuntimeError" in caplog.text
    assert "로그에 남기면 안 되는 내용" not in caplog.text
