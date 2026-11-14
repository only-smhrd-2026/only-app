"""가족방 목록의 사진 수·구성원 수·어르신 폰 (D70) — 가족 홈 '시작 3단계'와 어르신 바꾸기 판이 쓴다."""

from tests.conftest import add_photos, connect_device, make_room, signup


def test_room_list_shows_photos_members_and_device(client):
    signup(client)
    room = make_room(client)
    got = client.get("/api/rooms").json()[0]
    assert (got["photo_count"], got["member_count"], got["device_connected"]) == (0, 1, False)
    assert got["device_last_seen_at"] is None

    add_photos(room["room_id"])
    connect_device(client, room["room_id"])
    assert client.get("/api/devices/me").status_code == 200  # 폰이 서버에 한 번 옴 → 마지막 접속이 찍힌다
    got = client.get("/api/rooms").json()[0]
    assert (got["photo_count"], got["device_connected"]) == (3, True)
    assert got["device_last_seen_at"] is not None
