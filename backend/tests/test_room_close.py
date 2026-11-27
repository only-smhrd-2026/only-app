"""방장만 가족방을 닫을 수 있고, 기록은 보관하되 앱에서 더는 접근할 수 없다."""

from app.db import SessionLocal
from app.models import Diary, FamilyRoom, Photo
from tests.conftest import add_photos, connect_device, make_room, signup
from tests.test_family_diary import _post
from tests.test_member_nickname import login
from tests.test_room_settings import family as family


def test_owner_closes_room_for_everyone(client, family):
    owner, member, room_id, family_token = family
    path = f"/api/rooms/{room_id}"
    assert client.delete(path).status_code == 403
    login(client, owner)
    other_room = make_room(client)["room_id"]
    photo_id = add_photos(room_id)[0]
    photo_url = client.get(f"{path}/photos").json()["photos"][0]["url"]
    diary_id = _post(client, room_id).json()["diary_id"]
    connect_device(client, room_id)
    invite = client.post(f"{path}/invites", json={"kind": "ELDER_DEVICE"})
    device_token = invite.json()["url"].split("#", 1)[1]
    assert client.get("/api/devices/me").status_code == 200
    assert client.get(photo_url).status_code == 200
    assert client.get("/api/notifications").json()["notifications"]

    response = client.delete(path)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}
    assert client.delete(path).status_code == 404
    assert [room["room_id"] for room in client.get("/api/rooms").json()] == [other_room]
    assert client.get("/api/devices/me").status_code == 401
    assert client.post("/api/devices/connect", json={"token": device_token}).status_code == 410
    assert client.get("/api/notifications").json()["notifications"] == []

    login(client, member)
    assert client.get("/api/rooms").json() == []
    assert client.get(f"{path}/photos").status_code == 404
    assert client.get(photo_url).status_code == 404
    assert client.get(f"/api/diaries/{diary_id}").status_code == 404
    assert client.post("/api/invites/status", json={"token": family_token}).status_code == 404
    assert client.post("/api/invites/accept", json={"token": family_token, "relation_tag": "CHILD"}).status_code == 404

    with SessionLocal() as db:
        assert db.get(FamilyRoom, room_id).status == "CLOSED"
        assert db.get(Photo, photo_id) is not None
        assert db.get(Diary, diary_id) is not None


def test_closed_room_does_not_block_owner_withdrawal(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    assert client.delete(f"/api/rooms/{room_id}").status_code == 200
    response = client.post("/api/auth/withdraw", json={"password": "test1234", "transfers": []})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(FamilyRoom, room_id).status == "CLOSED"
