"""11/25 실사용: 로그인하면 초대받은 새 방 대신 옛 시험 방이 떴다 · 닫은 방의 어르신 기기가 그대로 열렸다."""

from app.db import SessionLocal
from app.models import FamilyRoom
from tests.conftest import make_room, setup_elder, signup
from tests.test_member_nickname import login


def test_rooms_newest_joined_first(client):
    owner = signup(client)
    older = make_room(client)["room_id"]  # 남이 먼저 만든 방 (번호가 작다)
    token = client.post(f"/api/rooms/{older}/invites", json={"kind": "FAMILY"}).json()["url"].split("#", 1)[1]
    signup(client)
    mine = make_room(client)["room_id"]  # 내 시험 방 (번호는 크지만 먼저 들어감)
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "CHILD"}).status_code == 200
    # 화면은 고른 방이 없으면 첫 방을 보인다 → 마지막에 들어간 방이 먼저
    assert [r["room_id"] for r in client.get("/api/rooms").json()] == [older, mine]
    login(client, owner)
    assert [r["room_id"] for r in client.get("/api/rooms").json()] == [older]


def test_closed_room_device_is_disconnected(client):
    room_id = setup_elder(client)["room_id"]
    assert client.get("/api/devices/me").status_code == 200
    with SessionLocal() as db:
        db.get(FamilyRoom, room_id).status = "CLOSED"
        db.commit()
    assert client.get("/api/devices/me").status_code == 401
