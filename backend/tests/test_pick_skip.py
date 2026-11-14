"""같은 사진을 두 번 건너뛸 때의 가족 알림, 옛 화면에서 누른 건너뛰기·다 들었어요(D65)를 검증한다."""

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


SKIP, LISTENED = "/api/elder/picks/today/skip", "/api/elder/picks/today/listened"


def _status(pick_id):
    with SessionLocal() as db:
        return db.get(DailyPick, pick_id).status


def test_skip_checks_the_pick_the_screen_was_showing(client):
    """화면이 보고 있던 pick 번호를 같이 보낸다 (D65): 날이 바뀐 옛 화면이면 409 이고 오늘 사진은 그대로,
    없는 번호·남의 가족방 번호는 404, 오늘 것이면 건너뛴다."""
    ctx = setup_elder(client)
    pick_id, yesterday = ctx["pick"]["pick_id"], today_kst() - timedelta(days=1)
    with SessionLocal() as db:
        old = DailyPick(room_id=ctx["room_id"], photo_id=ctx["pick"]["photo_id"], pick_date=yesterday)
        db.add(old)
        db.commit()
        old_id = old.pick_id
    stale = client.post(SKIP, json={"pick_id": old_id})
    assert stale.status_code == 409
    assert stale.json()["code"] == "PICK_EXPIRED"
    assert (_status(pick_id), _status(old_id)) == ("PENDING", "PENDING")  # 오늘 사진이 대신 건너뛰어지지 않는다
    assert client.post(SKIP, json={"pick_id": 999999}).status_code == 404

    other = setup_elder(client)  # 다른 가족방의 기기
    foreign = client.post(SKIP, json={"pick_id": pick_id})
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "PICK_NOT_FOUND"
    assert (_status(pick_id), _status(other["pick"]["pick_id"])) == ("PENDING", "PENDING")
    assert client.post(SKIP, json={"pick_id": other["pick"]["pick_id"]}).status_code == 200
    assert (_status(pick_id), _status(other["pick"]["pick_id"])) == ("PENDING", "SKIPPED")


def test_listened_goes_to_the_pick_of_that_talk(client):
    """[다 들었어요]는 대화 번호로 그 대화의 사진에 적힌다 — 자정을 넘겨 끝나도 새 날 사진에 남지 않는다 (D65)."""
    ctx = setup_elder(client)
    pick = ctx["pick"]
    sid = str(uuid.uuid4())
    body = {"session_id": sid, "kind": "MEMORY", "pick_id": pick["pick_id"], "photo_id": pick["photo_id"]}
    assert client.post("/api/elder/sessions", json=body).status_code == 201
    with SessionLocal() as db:  # 대화하는 사이 날이 바뀌었다 — 그 pick 은 어제 것이 되고 홈이 오늘 것을 새로 뽑는다
        db.get(DailyPick, pick["pick_id"]).pick_date = today_kst() - timedelta(days=1)
        db.commit()
    today = client.get("/api/elder/home").json()["today_pick"]
    assert today["pick_id"] != pick["pick_id"]

    assert client.post(LISTENED, json={"session_id": sid}).status_code == 200
    with SessionLocal() as db:
        assert db.get(DailyPick, pick["pick_id"]).listened_at is not None
        assert db.get(DailyPick, today["pick_id"]).listened_at is None

    assert client.post(LISTENED, json={"session_id": str(uuid.uuid4())}).status_code == 404  # 없는 대화
    setup_elder(client)  # 다른 가족방의 기기 — 남의 대화는 없는 것처럼
    foreign = client.post(LISTENED, json={"session_id": sid})
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "SESSION_NOT_FOUND"
