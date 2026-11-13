"""방장 설정·원격 반영·구성원 내보내기와 재요청을 확인한다."""

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import FamilyRoom, RoomMember
from tests.conftest import make_room, setup_elder, signup


def test_partial_settings(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    path = f"/api/rooms/{room_id}/settings"
    response = client.patch(path, json={"font_size": "XXL"})
    assert response.status_code == 200
    result = response.json()
    assert (result["font_size"], result["memory_time"], result["tts_speed"]) == ("XXL", "09:00:00", "0.85")
    assert client.patch(path, json={}).json() == result
    assert client.patch(path, json={"font_size": None}).json() == result


def test_elder_home_reflects_settings(client):
    ctx = setup_elder(client)
    response = client.patch(
        f"/api/rooms/{ctx['room_id']}/settings",
        json={"font_size": "L", "tts_speed": "1.00", "device_input_mode": "BUTTON"},
    )
    assert response.status_code == 200
    assert client.get("/api/elder/home").json()["settings"] == {
        "font_size": "L",
        "tts_speed": "1.00",
        "input_mode": "BUTTON",
    }


def test_time_validation_is_atomic(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    path = f"/api/rooms/{room_id}/settings"
    response = client.patch(path, json={"memory_time": "10:00"})
    assert response.status_code == 200
    assert response.json()["memory_time"] == "10:00:00"
    for bad_time in ("10:30", "10:00:01", "10:00:00.000001"):
        response = client.patch(path, json={"memory_time": bad_time, "font_size": "L"})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION"
    with SessionLocal() as db:
        room = db.get(FamilyRoom, room_id)
        assert room.memory_time.isoformat() == "10:00:00"
        assert room.font_size == "XL"
    response = client.patch(path, json={"diary_time": "20:30"})
    assert response.status_code == 200
    assert response.json()["diary_time"] == "20:30:00"


@pytest.mark.parametrize("body", [{"font_size": "XXXL"}, {"tts_speed": "0.9"}, {"device_input_mode": "TEXT"}])
def test_invalid_settings(client, body):
    signup(client)
    room_id = make_room(client)["room_id"]
    response = client.patch(f"/api/rooms/{room_id}/settings", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION"


@pytest.fixture
def family(client):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    invite = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"})
    token = invite.json()["url"].split("#", 1)[1]
    member = signup(client)
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "GRANDCHILD"}).status_code == 200
    return owner, member, room_id, token


def test_settings_and_removal_permissions(client, family):
    owner, member, room_id, _ = family

    def check(status, code):
        responses = [
            client.patch(f"/api/rooms/{room_id}/settings", json={"font_size": "L"}),
            client.delete(f"/api/rooms/{room_id}/members/{member['user_id']}"),
        ]
        for response in responses:
            assert response.status_code == status
            assert response.json()["code"] == code

    check(403, "NOT_OWNER")
    signup(client)
    check(404, "ROOM_NOT_FOUND")
    client.cookies.clear()
    check(401, "AUTH_REQUIRED")


def test_remove_member_is_idempotent_and_blocks_access(client, family):
    owner, member, room_id, token = family
    client.post("/api/auth/login", json={"email": owner["email"], "password": "test1234"})
    path = f"/api/rooms/{room_id}/members/{member['user_id']}"
    response = client.delete(path)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    with SessionLocal() as db:
        row = db.scalar(
            select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == member["user_id"])
        )
        removed_at = row.removed_at
        assert removed_at is not None
    assert client.delete(path).status_code == 200
    with SessionLocal() as db:
        row = db.scalar(
            select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == member["user_id"])
        )
        assert row.removed_at == removed_at
    response = client.delete(f"/api/rooms/{room_id}/members/{owner['user_id']}")
    assert response.status_code == 400
    assert response.json()["code"] == "CANNOT_REMOVE_OWNER"
    response = client.delete(f"/api/rooms/{room_id}/members/999999")
    assert response.status_code == 404
    assert response.json()["code"] == "MEMBER_NOT_FOUND"
    client.post("/api/auth/login", json={"email": member["email"], "password": "test1234"})
    assert client.get("/api/rooms").json() == []
    response = client.get(f"/api/rooms/{room_id}/diaries")
    assert response.status_code == 404
    assert response.json()["code"] == "ROOM_NOT_FOUND"
    response = client.post("/api/invites/accept", json={"token": token, "relation_tag": "GRANDCHILD"})
    assert response.status_code == 403
    assert response.json()["code"] == "MEMBER_REMOVED"
