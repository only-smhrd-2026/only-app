"""마음 체크 초대 간격·오늘의 한 장 상태·기기 인증을 확인한다."""

from datetime import timedelta

from sqlalchemy import select

from app.config import today_kst
from app.db import SessionLocal
from app.models import DailyPick, MoodCheck
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
