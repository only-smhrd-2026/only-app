"""기기 해제 즉시 기존 쿠키가 차단되고 방장만 해제할 수 있는지 확인한다."""

from app.config import now_kst
from app.db import SessionLocal
from app.models import FamilyRoom
from tests.conftest import connect_device, setup_elder, signup


def test_revoke_twice_and_reconnect(client):
    room_id = setup_elder(client)["room_id"]
    path = f"/api/rooms/{room_id}/device"
    assert client.get("/api/elder/home").status_code == 200
    with SessionLocal() as db:
        room = db.get(FamilyRoom, room_id)
        room.device_push_token = "test-push-token"
        room.device_last_seen_at = now_kst()
        room.device_perm_notification = True
        room.device_perm_mic = True
        room.device_perm_camera = True
        room.device_input_mode = "BUTTON"
        db.commit()
    response = client.delete(path)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    response = client.get("/api/elder/home")
    assert response.status_code == 401
    assert response.json()["code"] == "DEVICE_REQUIRED"
    with SessionLocal() as db:
        room = db.get(FamilyRoom, room_id)
        assert room.device_token_hash is None
        assert room.device_push_token is None
        assert room.device_connected_at is None
        assert room.device_last_seen_at is None
        assert room.device_perm_notification is True
        assert room.device_perm_mic is True
        assert room.device_perm_camera is True
        assert room.device_input_mode == "BUTTON"
    assert client.delete(path).json() == {"ok": True}
    connect_device(client, room_id)
    assert client.get("/api/elder/home").status_code == 200
    with SessionLocal() as db:
        room = db.get(FamilyRoom, room_id)
        assert room.device_token_hash is not None
        assert room.device_connected_at is not None


def test_non_owner_cannot_revoke(client):
    room_id = setup_elder(client)["room_id"]
    invite = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"})
    assert invite.status_code == 201
    token = invite.json()["url"].split("#", 1)[1]
    signup(client)
    response = client.post("/api/invites/accept", json={"token": token, "relation_tag": "GRANDCHILD"})
    assert response.status_code == 200
    response = client.delete(f"/api/rooms/{room_id}/device")
    assert response.status_code == 403
    assert response.json()["code"] == "NOT_OWNER"
    assert client.get("/api/elder/home").status_code == 200


def test_non_member_and_login_required(client):
    room_id = setup_elder(client)["room_id"]
    with SessionLocal() as db:
        original_hash = db.get(FamilyRoom, room_id).device_token_hash
    signup(client)
    for hidden in (room_id, 999999):
        response = client.delete(f"/api/rooms/{hidden}/device")
        assert response.status_code == 404
        assert response.json()["code"] == "ROOM_NOT_FOUND"
    client.cookies.delete("session")
    response = client.delete(f"/api/rooms/{room_id}/device")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
    with SessionLocal() as db:
        assert db.get(FamilyRoom, room_id).device_token_hash == original_hash
    assert client.get("/api/elder/home").status_code == 200
