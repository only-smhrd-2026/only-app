"""같은 사진을 두 번 건너뛸 때의 가족 알림을 검증한다."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import now_kst, today_kst
from app.db import SessionLocal
from app.models import DailyPick, FamilyRoom, Notification
from tests.conftest import make_room, setup_elder


def _past_skip(db, ctx, days_ago, photo_id=None, room_id=None):
    db.add(
        DailyPick(
            room_id=room_id if room_id is not None else ctx["room_id"],
            photo_id=photo_id if photo_id is not None else ctx["pick"]["photo_id"],
            pick_date=today_kst() - timedelta(days=days_ago),
            status="SKIPPED",
            skipped_at=now_kst() - timedelta(days=days_ago),
        )
    )


def _alerts(db, room_id):
    return db.scalars(
        select(Notification).where(Notification.room_id == room_id, Notification.kind == "PICK_SKIPPED_2X")
    ).all()


def test_second_skip_alert_and_third_skip_no_more_alerts(client):
    ctx = setup_elder(client)
    with SessionLocal() as db:
        _past_skip(db, ctx, 1)
        db.commit()

    response = client.post("/api/elder/picks/today/skip")
    assert response.status_code == 200, response.text
    # 홈은 같은 pick·사진을 SKIPPED 로 돌려준다(다시 안 뽑음 → 그날 팝업이 다시 안 뜸).
    assert client.get("/api/elder/home").json()["today_pick"] == ctx["pick"] | {"status": "SKIPPED"}
    with SessionLocal() as db:
        pick = db.get(DailyPick, ctx["pick"]["pick_id"])
        assert pick.status == "SKIPPED"
        assert pick.skipped_at is not None
        alerts = _alerts(db, ctx["room_id"])
        assert len(alerts) == 1
        room = db.get(FamilyRoom, ctx["room_id"])
        assert alerts[0].title == f"{room.elder_name} 님이 같은 사진을 두 번 넘기셨어요"

    # 같은 날 재요청하면 상태·알림·건너뛴 시각을 그대로 둔다.
    assert client.post("/api/elder/picks/today/skip").status_code == 200
    with SessionLocal() as db:
        assert db.get(DailyPick, ctx["pick"]["pick_id"]).status == "SKIPPED"
        assert db.get(DailyPick, ctx["pick"]["pick_id"]).skipped_at == pick.skipped_at
        assert len(_alerts(db, ctx["room_id"])) == 1
        # 오늘 기록을 과거로 옮기고, 같은 사진의 세 번째 날짜를 준비한다.
        db.get(DailyPick, ctx["pick"]["pick_id"]).pick_date = today_kst() - timedelta(days=2)
        db.flush()
        db.add(DailyPick(room_id=ctx["room_id"], photo_id=ctx["pick"]["photo_id"], pick_date=today_kst()))
        db.commit()

    assert client.post("/api/elder/picks/today/skip").status_code == 200
    with SessionLocal() as db:
        assert len(_alerts(db, ctx["room_id"])) == 1


@pytest.mark.parametrize("other_room", [False, True])
def test_other_photo_or_room_skips_do_not_count(client, other_room):
    ctx = setup_elder(client)
    room_id = make_room(client)["room_id"] if other_room else ctx["room_id"]
    photo_id = (
        ctx["pick"]["photo_id"]
        if other_room
        else next(pid for pid in ctx["photo_ids"] if pid != ctx["pick"]["photo_id"])
    )
    with SessionLocal() as db:
        _past_skip(db, ctx, 1, photo_id=photo_id, room_id=room_id)
        db.commit()
    assert client.post("/api/elder/picks/today/skip").status_code == 200
    with SessionLocal() as db:
        assert _alerts(db, ctx["room_id"]) == []


@pytest.mark.parametrize("status", ["SKIPPED", "COMPLETED"])
def test_finished_pick_is_unchanged(client, status):
    ctx = setup_elder(client)
    with SessionLocal() as db:
        _past_skip(db, ctx, 1)
        db.get(DailyPick, ctx["pick"]["pick_id"]).status = status
        db.commit()
    assert client.post("/api/elder/picks/today/skip").status_code == 200
    with SessionLocal() as db:
        pick = db.get(DailyPick, ctx["pick"]["pick_id"])
        assert pick.status == status
        assert pick.skipped_at is None
        assert _alerts(db, ctx["room_id"]) == []


@pytest.mark.parametrize("status", ["COMPLETED", "EXPIRED", "PENDING"])
def test_past_unskipped_same_photo_not_counted_or_changed(client, status):
    """같은 사진의 지난 날 행이라도 건너뛴 기록(skipped_at)이 없으면 세지 않고, 오늘 것이 아니니 바꾸지도 않는다."""
    ctx = setup_elder(client)
    with SessionLocal() as db:
        past = DailyPick(
            room_id=ctx["room_id"],
            photo_id=ctx["pick"]["photo_id"],
            pick_date=today_kst() - timedelta(days=1),
            status=status,
        )
        db.add(past)
        db.commit()
        past_id = past.pick_id
    assert client.post("/api/elder/picks/today/skip").status_code == 200
    with SessionLocal() as db:
        assert _alerts(db, ctx["room_id"]) == []
        past = db.get(DailyPick, past_id)
        assert (past.status, past.skipped_at) == (status, None)


def test_skipped_then_completed_still_counts(client):
    """건너뛴 pick 으로 대화를 끝내 COMPLETED 로 덮여도 건너뛴 기록은 남아, 같은 사진 알림이 또 가지 않는다."""
    ctx = setup_elder(client)
    pick_id = ctx["pick"]["pick_id"]
    with SessionLocal() as db:
        _past_skip(db, ctx, 1)
        db.commit()
    # 대화를 먼저 연 뒤에 건너뛴 경우(창 두 개)만 남는다 — 건너뛴 뒤에는 새 대화가 안 열린다(409 PICK_SKIPPED, D45 ④).
    # 열려 있던 대화를 끝내면 pick 이 COMPLETED 로 덮인다.
    sid = str(uuid.uuid4())
    body = {"session_id": sid, "kind": "MEMORY", "pick_id": pick_id}
    assert client.post("/api/elder/sessions", json=body).status_code == 201
    assert client.post("/api/elder/picks/today/skip").status_code == 200  # 두 번째 건너뛰기 → 알림 1건
    late = client.post("/api/elder/sessions", json=body | {"session_id": str(uuid.uuid4())})
    assert late.status_code == 409 and late.json()["code"] == "PICK_SKIPPED"
    assert client.post(f"/api/elder/sessions/{sid}/end", json={"reason": "USER_STOP"}).status_code == 200
    with SessionLocal() as db:
        pick = db.get(DailyPick, pick_id)
        assert pick.status == "COMPLETED" and pick.skipped_at is not None
        assert len(_alerts(db, ctx["room_id"])) == 1
        # 그 기록을 과거로 옮기고, 같은 사진이 다시 뽑힌 오늘을 준비한다(세 번째 건너뛰기).
        pick.pick_date = today_kst() - timedelta(days=2)
        db.flush()
        db.add(DailyPick(room_id=ctx["room_id"], photo_id=ctx["pick"]["photo_id"], pick_date=today_kst()))
        db.commit()

    assert client.post("/api/elder/picks/today/skip").status_code == 200
    with SessionLocal() as db:
        assert len(_alerts(db, ctx["room_id"])) == 1
