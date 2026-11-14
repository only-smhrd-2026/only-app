"""GET /api/devices/me — 홈 화면 아이콘으로 열 때(/start) 어르신 폰인지 가린다 (D68)."""

from tests.conftest import add_photos, connect_device, make_room, signup


def test_device_me_needs_device_cookie(client):
    signup(client)
    room = make_room(client)
    r = client.get("/api/devices/me")
    assert r.status_code == 401  # 가족 로그인만으로는 어르신 폰이 아니다
    assert r.json()["code"] == "DEVICE_REQUIRED"
    add_photos(room["room_id"])
    connect_device(client, room["room_id"])
    r = client.get("/api/devices/me")
    assert r.status_code == 200
    assert r.json()["room_id"] == room["room_id"]
