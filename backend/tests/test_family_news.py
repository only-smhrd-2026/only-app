"""어르신 가족 소식: 안 들은 가족 일기만 조회하고 첫 열람 시각을 유지한다."""

import uuid

from app.db import SessionLocal
from app.models import Diary, FamilyRoom
from tests.conftest import setup_elder, signup


def _diary(room_id, author_type="FAMILY", status="POSTED"):
    with SessionLocal() as db:
        diary = Diary(
            room_id=room_id,
            author_type=author_type,
            author_user_id=db.get(FamilyRoom, room_id).owner_user_id if author_type == "FAMILY" else None,
            body="오늘 공원을 걸었어요.",
            mood="SUNNY",
            illustration_type="NONE",
            request_id=uuid.uuid4(),
            status=status,
        )
        db.add(diary)
        db.commit()
        return diary.diary_id


def test_unread_list_and_home_count(client):
    room_id = setup_elder(client)["room_id"]
    first, second = _diary(room_id), _diary(room_id)
    _diary(room_id, "ELDER")
    _diary(room_id, status="DELETED")
    response = client.get("/api/elder/family-news")
    assert response.status_code == 200, response.text
    assert [d["diary_id"] for d in response.json()["diaries"]] == [second, first]
    assert client.get("/api/elder/home").json()["unread_family_news"] == 2


def test_mark_read_twice_preserves_first_time(client):
    room_id = setup_elder(client)["room_id"]
    diary_id, remaining = _diary(room_id), _diary(room_id)
    path = f"/api/elder/diaries/{diary_id}/read"
    assert client.post(path).status_code == 204
    with SessionLocal() as db:
        first_time = db.get(Diary, diary_id).elder_read_at
        assert first_time is not None
    assert client.post(path).status_code == 204
    with SessionLocal() as db:
        assert db.get(Diary, diary_id).elder_read_at == first_time
    assert [d["diary_id"] for d in client.get("/api/elder/family-news").json()["diaries"]] == [remaining]
    assert client.get("/api/elder/home").json()["unread_family_news"] == 1


def test_other_room_and_missing_diary_hidden(client):
    old_room = setup_elder(client)["room_id"]
    diary_id = _diary(old_room)
    setup_elder(client)
    assert client.get("/api/elder/family-news").json()["diaries"] == []
    for hidden in (diary_id, 999999):
        response = client.post(f"/api/elder/diaries/{hidden}/read")
        assert response.status_code == 404
        assert response.json()["code"] == "DIARY_NOT_FOUND"
    with SessionLocal() as db:
        assert db.get(Diary, diary_id).elder_read_at is None


def test_elder_and_deleted_diaries_cannot_be_marked_read(client):
    room_id = setup_elder(client)["room_id"]
    for diary_id in (_diary(room_id, "ELDER"), _diary(room_id, status="DELETED")):
        response = client.post(f"/api/elder/diaries/{diary_id}/read")
        assert response.status_code == 404
        assert response.json()["code"] == "DIARY_NOT_FOUND"


def test_family_cookie_is_not_device_auth(client):
    signup(client)
    for response in (client.get("/api/elder/family-news"), client.post("/api/elder/diaries/999999/read")):
        assert response.status_code == 401
        assert response.json()["code"] == "DEVICE_REQUIRED"
