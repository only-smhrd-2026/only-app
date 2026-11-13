"""마음 체크 초대 간격·오늘의 한 장 상태·기기 인증을 확인한다."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import today_kst
from app.db import SessionLocal
from app.models import DailyPick, FamilyRoom, MoodCheck
from app.routers import mood
from tests.conftest import setup_elder


def test_pending_and_skipped(client):
    setup_elder(client)
    response = client.get("/api/elder/mood-check")
    assert response.status_code == 200
    assert response.json() == {"due": False}
    assert client.post("/api/elder/picks/today/skip").status_code == 200
    assert client.get("/api/elder/mood-check").json() == {"due": True}


def test_interval_boundary(client):
    ctx = setup_elder(client)
    client.post("/api/elder/picks/today/skip")
    with SessionLocal() as db:
        check = MoodCheck(
            room_id=ctx["room_id"],
            check_date=today_kst() - timedelta(days=13),
            answers=[0] * 8,
            total=0,
            level="USUAL",
        )
        db.add(check)
        db.commit()
        assert client.get("/api/elder/mood-check").json() == {"due": False}
        check.check_date = today_kst() - timedelta(days=14)
        db.commit()
    assert client.get("/api/elder/mood-check").json() == {"due": True}


def test_completed_and_no_pick(client):
    ctx = setup_elder(client)
    with SessionLocal() as db:
        pick = db.scalar(select(DailyPick).where(DailyPick.room_id == ctx["room_id"]))
        pick.status = "COMPLETED"
        db.commit()
        assert client.get("/api/elder/mood-check").json() == {"due": True}
        pick.pick_date = today_kst() - timedelta(days=1)
        db.commit()
    assert client.get("/api/elder/mood-check").json() == {"due": True}
    with SessionLocal() as db:
        assert (
            db.scalar(select(DailyPick).where(DailyPick.room_id == ctx["room_id"], DailyPick.pick_date == today_kst()))
            is None
        )


def test_device_required(client):
    setup_elder(client)
    client.cookies.delete("device")
    response = client.get("/api/elder/mood-check")
    assert response.status_code == 401
    assert response.json()["code"] == "DEVICE_REQUIRED"


def test_level_boundaries():
    assert [mood.check_level(t) for t in (0, 4, 5, 9, 10, 24)] == ["USUAL", "USUAL", "DOWN", "DOWN", "HARD", "HARD"]


def test_save_keeps_first_answers_and_consent(client):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    answers = [1, 1, 1, 1, 1, 0, 0, 0]
    response = client.post("/api/elder/mood-check", json={"answers": answers})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    with SessionLocal() as db:
        checks = db.scalars(select(MoodCheck).where(MoodCheck.room_id == room_id)).all()
        assert len(checks) == 1
        assert checks[0].check_date == today_kst()
        assert (checks[0].answers, checks[0].total, checks[0].level) == (answers, 5, "DOWN")
        consent = db.get(FamilyRoom, room_id).mood_check_consent_at
        assert consent is not None
    response = client.post("/api/elder/mood-check", json={"answers": [3] * 8})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    with SessionLocal() as db:
        checks = db.scalars(select(MoodCheck).where(MoodCheck.room_id == room_id)).all()
        assert len(checks) == 1
        assert (checks[0].answers, checks[0].total, checks[0].level) == (answers, 5, "DOWN")
        assert db.get(FamilyRoom, room_id).mood_check_consent_at == consent
    assert client.get("/api/elder/mood-check").json() == {"due": False}
    response = client.get(f"/api/rooms/{room_id}/mood-week")
    assert response.status_code == 200
    assert response.json()["last_check"] == {"check_date": today_kst().isoformat(), "level": "DOWN"}
    assert "total" not in response.text
    assert "answers" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"answers": [0] * 7},
        {"answers": [0] * 9},
        {"answers": [4] + [0] * 7},
        {"answers": [-1] + [0] * 7},
        {},
    ],
)
def test_invalid_answers_do_not_save(client, body):
    ctx = setup_elder(client)
    response = client.post("/api/elder/mood-check", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"
    with SessionLocal() as db:
        assert db.scalars(select(MoodCheck).where(MoodCheck.room_id == ctx["room_id"])).all() == []
        assert db.get(FamilyRoom, ctx["room_id"]).mood_check_consent_at is None


def test_save_requires_device(client):
    setup_elder(client)
    client.cookies.delete("device")
    response = client.post("/api/elder/mood-check", json={"answers": [0] * 8})
    assert response.status_code == 401
    assert response.json()["code"] == "DEVICE_REQUIRED"
