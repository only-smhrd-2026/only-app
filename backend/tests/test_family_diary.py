"""가족 일기 올리기 (POST /rooms/{id}/diaries, FR-DI-008): 같은 가족방 + 같은 request_id 는 일기 1개."""

import uuid

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Diary
from tests.conftest import add_photos, make_room, setup_elder, signup


def _post(client, room_id, **extra):
    data = {"request_id": str(uuid.uuid4()), "body": "오늘 공원을 걸었어요.", "mood": "SUNNY"} | extra
    return client.post(f"/api/rooms/{room_id}/diaries", json=data)


def _count(request_id):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Diary).where(Diary.request_id == uuid.UUID(request_id)))


def test_same_request_twice_makes_one_diary(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    request_id = str(uuid.uuid4())
    first = _post(client, room_id, request_id=request_id)
    second = _post(client, room_id, request_id=request_id, body="다른 글")
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["diary_id"] == second.json()["diary_id"]
    assert second.json()["body"] == "오늘 공원을 걸었어요."  # 처음 글 그대로
    assert _count(request_id) == 1


def test_response_shape(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    d = _post(client, room_id, body="  오늘 공원을 걸었어요.  ").json()
    assert d["author_type"] == "FAMILY"
    assert d["author_name"] == "테스터"
    assert d["body"] == "오늘 공원을 걸었어요."
    assert d["read_by_me"] is True
    assert d["illustration_type"] == "NONE"


def test_same_request_in_two_rooms_makes_two(client):
    signup(client)
    rooms = [make_room(client)["room_id"], make_room(client)["room_id"]]
    request_id = str(uuid.uuid4())
    ids = {_post(client, r, request_id=request_id).json()["diary_id"] for r in rooms}
    assert len(ids) == 2
    assert _count(request_id) == 2


def test_elder_sees_family_diary(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _post(client, room_id).json()["diary_id"]
    news = client.get("/api/elder/family-news").json()["diaries"]
    assert [d["diary_id"] for d in news] == [diary_id]
    assert client.get("/api/elder/home").json()["unread_family_news"] == 1


def test_login_and_member_required(client):
    assert _post(client, 1).status_code == 401
    signup(client)
    room_id = make_room(client)["room_id"]
    r = _post(client, room_id + 999)
    assert r.status_code == 404
    assert r.json()["code"] == "ROOM_NOT_FOUND"
    signup(client)  # 다른 계정으로 로그인
    r = _post(client, room_id)
    assert r.status_code == 404
    assert r.json()["code"] == "ROOM_NOT_FOUND"


def test_bad_body_and_mood(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    blank = _post(client, room_id, body="   ")
    assert blank.status_code == 422
    assert blank.json()["detail"] == "일기 내용을 적어 주세요"
    assert _post(client, room_id, body="가" * 2001).status_code == 422
    assert _post(client, room_id, mood="HAPPY").status_code == 422


def test_photo_must_be_this_room(client):
    signup(client)
    room_id, other_id = make_room(client)["room_id"], make_room(client)["room_id"]
    mine, other = add_photos(room_id, 1)[0], add_photos(other_id, 1)[0]
    ok = _post(client, room_id, photo_id=mine)
    assert ok.status_code == 201, ok.text
    assert ok.json()["illustration_type"] == "PHOTO"
    bad = _post(client, room_id, photo_id=other)
    assert bad.status_code == 404
    assert bad.json()["code"] == "PHOTO_NOT_FOUND"


def test_unknown_session_id_is_ignored(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    r = _post(client, room_id, session_id=str(uuid.uuid4()))
    assert r.status_code == 201, r.text
