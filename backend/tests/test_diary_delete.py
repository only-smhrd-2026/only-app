"""가족 일기 삭제는 작성자만 가능하고 기존 파일은 보존한다."""

from app.db import SessionLocal
from app.models import Diary, RoomMember
from tests.conftest import setup_elder, signup
from tests.test_family_diary import _post
from tests.test_family_news import _diary


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
        assert db.get(Diary, diary["diary_id"]).status == "DELETED"


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
