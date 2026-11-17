"""세션 마무리·기기 연결의 중복 요청 (NFR-DV-005·006)."""

import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.models import DailyPick, Notification, TalkSession
from tests.conftest import add_photos, make_room, setup_elder, signup
from tests.test_session_stub import _create


def test_end_twice_preserves_time_pick_and_quiz_records(client, question_bank):
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    for _ in range(3):
        assert (
            client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "기억나요", "input_type": "CHIP"}).status_code
            == 200
        )
    url = f"/api/elder/sessions/{sid}/end"
    first = client.post(url, json={"reason": "USER_STOP"})
    assert first.status_code == 200
    with SessionLocal() as db:
        session = db.get(TalkSession, uuid.UUID(sid))
        before = (session.ended_at, session.turns, db.get(DailyPick, ctx["pick"]["pick_id"]).status)
        assert sum(bool(t.get("question_code")) for t in session.turns) == 1
    second = client.post(url, json={"reason": "COMPLETED"})
    assert second.status_code == 200 and second.json() == first.json()
    with SessionLocal() as db:
        session = db.get(TalkSession, uuid.UUID(sid))
        after = (session.ended_at, session.turns, db.get(DailyPick, ctx["pick"]["pick_id"]).status)
        assert before == after and session.end_reason == "USER_STOP"


def test_device_link_twice_notifies_each_family_member_once(client):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    add_photos(room_id)
    invite = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"})
    token = invite.json()["url"].split("#", 1)[1]
    member = signup(client)
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "CHILD"}).status_code == 200
    client.post("/api/auth/login", json={"email": owner["email"], "password": "test1234"})
    invite = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "ELDER_DEVICE"})
    body = {"token": invite.json()["url"].split("#", 1)[1]}
    assert client.post("/api/devices/connect", json=body).status_code == 200
    second = client.post("/api/devices/connect", json=body)
    assert second.status_code == 410 and second.json()["code"] == "INVITE_INVALID"
    with SessionLocal() as db:
        notices = db.scalars(
            select(Notification).where(Notification.room_id == room_id, Notification.kind == "DEVICE_CONNECTED")
        ).all()
        assert sorted(n.target_user_id for n in notices) == sorted([owner["user_id"], member["user_id"]])
