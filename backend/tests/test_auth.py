"""가족 가입 → 가족방 → 기기 링크 → 어르신 홈 → 사진까지 이어지는지 (초석 C·F 완료 기준)."""

from tests.conftest import add_photos, connect_device, make_room, signup


def test_family_to_elder_flow(client):
    user = signup(client)
    assert client.get("/api/auth/me").json()["email"] == user["email"]

    bad = client.post("/api/auth/login", json={"email": user["email"], "password": "wrong-pass"})
    assert bad.status_code == 401 and bad.json()["code"] == "LOGIN_FAILED"

    room = make_room(client)
    assert room["is_owner"] is True
    assert [r["room_id"] for r in client.get("/api/rooms").json()] == [room["room_id"]]

    need = client.post(f"/api/rooms/{room['room_id']}/invites", json={"kind": "ELDER_DEVICE"})
    assert need.status_code == 409 and need.json()["code"] == "NEED_PHOTOS"

    add_photos(room["room_id"], 3)
    inv = client.post(f"/api/rooms/{room['room_id']}/invites", json={"kind": "ELDER_DEVICE"}).json()
    token = inv["url"].split("#", 1)[1]
    status = client.post("/api/invites/status", json={"token": token}).json()
    assert status == {**status, "kind": "ELDER_DEVICE", "elder_name": "순자", "valid": True}

    dev = client.post("/api/devices/connect", json={"token": token})
    assert dev.status_code == 200 and dev.json()["elder_name"] == "순자"
    assert client.post("/api/devices/connect", json={"token": token}).status_code == 410  # 1회용

    home = client.get("/api/elder/home").json()
    assert home["today_pick"] is not None and home["today_pick"]["status"] == "PENDING"
    media = client.get(home["today_pick"]["photo_url"])
    assert media.status_code == 200 and media.headers["content-type"] == "image/jpeg"

    perm = client.patch("/api/devices/me/permissions", json={"perm_mic": True, "perm_camera": False})
    assert perm.json()["perm_mic"] is True and perm.json()["perm_camera"] is False

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

    signup(client)  # 다른 가족 계정은 남의 가족방을 못 본다
    assert client.get(f"/api/rooms/{room['room_id']}/invites").status_code == 403
    assert client.get(home["today_pick"]["photo_url"]).status_code == 404  # 구성원 아닌 가족 쿠키 → 존재 비노출
    client.post("/api/auth/logout")
    assert client.get(home["today_pick"]["photo_url"]).status_code == 200  # 기기 쿠키만 남으면 그대로 유효


def test_family_invite_accept(client):
    owner = signup(client)
    room = make_room(client)
    inv = client.post(f"/api/rooms/{room['room_id']}/invites", json={"kind": "FAMILY"}).json()
    token = inv["url"].split("#", 1)[1]
    assert "/join#" in inv["url"]

    signup(client)  # 두 번째 가족
    joined = client.post("/api/invites/accept", json={"token": token, "relation_tag": "GRANDCHILD", "name": "손주"})
    assert joined.status_code == 200 and joined.json()["room_id"] == room["room_id"]
    assert joined.json()["is_owner"] is False
    assert client.get("/api/auth/me").json()["name"] == "손주"
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "GRANDCHILD"}).status_code == 200
    assert len(client.get("/api/rooms").json()) == 1

    client.post("/api/auth/login", json={"email": owner["email"], "password": "test1234"})
    assert client.delete(f"/api/rooms/{room['room_id']}/invites/{inv['invite_id']}").status_code == 200
    assert client.post("/api/invites/status", json={"token": token}).json()["valid"] is False


def test_device_requires_connection(client):
    connect_device  # noqa: B018  (헬퍼 존재 확인)
    assert client.get("/api/elder/home").status_code == 401
