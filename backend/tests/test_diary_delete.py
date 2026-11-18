"""가족 일기 삭제 권한과 본문·첨부 삭제를 확인한다."""

from app.db import SessionLocal
from app.models import Diary, Photo, RoomMember
from app.services import storage
from tests.conftest import setup_elder, signup
from tests.test_family_diary import _post
from tests.test_family_news import _diary
from tests.test_photo_delete import upload


def test_delete_own_diary_hides_from_family_and_elder(client):
    room = setup_elder(client)["room_id"]
    diary = _post(client, room).json()
    assert diary["is_mine"] is True
    path = f"/api/diaries/{diary['diary_id']}"
    assert client.get(path).json()["is_mine"] is True
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    assert client.delete(path).status_code == 404
    assert diary["diary_id"] not in [d["diary_id"] for d in client.get(f"/api/rooms/{room}/diaries").json()["diaries"]]
    assert diary["diary_id"] not in [d["diary_id"] for d in client.get("/api/elder/family-news").json()["diaries"]]
    with SessionLocal() as db:
        stored = db.get(Diary, diary["diary_id"])
        assert stored.status == "DELETED"
        assert stored.body == ""
        assert stored.reactions == []


def test_delete_diary_removes_attached_photo(client):
    room = setup_elder(client)["room_id"]
    photo = upload(client, room, "FAMILY_DIARY")
    photo_id = photo["photo_id"]
    diary = _post(client, room, photo_id=photo_id)
    assert diary.status_code == 201, diary.text
    with SessionLocal() as db:
        stored = db.get(Photo, photo_id)
        key = stored.object_key
        thumb = key.rsplit("/", 1)[0] + "/1.jpg"
        stored.thumb_key = thumb
        storage.put(thumb, b"thumbnail")
        db.commit()
    assert client.delete(f"/api/diaries/{diary.json()['diary_id']}").status_code == 204
    with SessionLocal() as db:
        assert db.get(Photo, photo_id).status == "DELETED"
    assert storage.get(key) is None
    assert storage.get(thumb) is None
    assert client.get(photo["url"]).status_code == 404


def test_delete_permissions_and_is_mine(client):
    room = setup_elder(client)["room_id"]
    own = _post(client, room).json()["diary_id"]
    elder = _diary(room, "ELDER")
    response = client.delete(f"/api/diaries/{elder}")
    assert response.status_code == 403 and response.json()["code"] == "NOT_AUTHOR"
    other = signup(client)
    assert client.delete(f"/api/diaries/{own}").status_code == 404
    with SessionLocal() as db:
        db.add(RoomMember(room_id=room, user_id=other["user_id"], relation_tag="CHILD"))
        db.commit()
    response = client.delete(f"/api/diaries/{own}")
    assert response.status_code == 403 and response.json()["code"] == "NOT_AUTHOR"
    second = _post(client, room).json()["diary_id"]
    flags = {d["diary_id"]: d["is_mine"] for d in client.get(f"/api/rooms/{room}/diaries").json()["diaries"]}
    assert flags == {own: False, elder: False, second: True}
    client.cookies.clear()
    assert client.delete(f"/api/diaries/{second}").status_code == 401


def test_delete_diary_keeps_photo_it_does_not_own(client):
    """남이 올린 가족 일기 사진이 붙은 일기를 지워도 그 사진은 남는다 (11/18 다듬기 — 지우기 쪽 안전망)."""
    room = setup_elder(client)["room_id"]
    photo_id = upload(client, room, "FAMILY_DIARY")["photo_id"]  # 방장이 올린 사진
    other = signup(client)  # 이제부터 다른 가족으로 부른다
    with SessionLocal() as db:
        db.add(RoomMember(room_id=room, user_id=other["user_id"], relation_tag="CHILD"))
        db.commit()
    diary_id = _post(client, room).json()["diary_id"]
    with SessionLocal() as db:  # 올릴 때 검사(post_family_diary)가 생기기 전에 붙은 일기를 흉내
        db.get(Diary, diary_id).photo_id = photo_id
        db.commit()
    assert client.delete(f"/api/diaries/{diary_id}").status_code == 204
    with SessionLocal() as db:
        assert db.get(Photo, photo_id).status == "ACTIVE"
