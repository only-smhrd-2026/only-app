"""자발적 나가기·재가입·게시물 보존과 내보내기 차이를 확인한다."""

from tests.conftest import make_room, setup_elder, signup
from tests.test_family_diary import _post
from tests.test_family_news import _diary
from tests.test_member_nickname import login
from tests.test_room_settings import family as family


def test_leave_and_rejoin_preserves_diary(client, family):
    owner, member, room, token = family
    diary = _post(client, room).json()["diary_id"]
    path = f"/api/rooms/{room}/leave"
    assert client.post(path).json() == {"ok": True}
    assert all(r["room_id"] != room for r in client.get("/api/rooms").json())
    assert client.get(f"/api/diaries/{diary}").status_code == 404
    assert client.get(f"/api/rooms/{room}/diaries").status_code == 404
    assert client.post(path).status_code == 404
    login(client, owner)
    remaining = client.get(f"/api/diaries/{diary}")
    assert remaining.status_code == 200 and remaining.json()["author_nickname"] is None
    response = client.post(path)
    assert response.status_code == 400 and response.json()["code"] == "OWNER_CANNOT_LEAVE"
    login(client, member)
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "CHILD"}).status_code == 200
    assert any(r["room_id"] == room for r in client.get("/api/rooms").json())
    login(client, owner)
    client.delete(f"/api/rooms/{room}/members/{member['user_id']}")
    login(client, member)
    response = client.post("/api/invites/accept", json={"token": token, "relation_tag": "CHILD"})
    assert response.status_code == 403 and response.json()["code"] == "MEMBER_REMOVED"


def test_leave_other_room_and_login(client):
    signup(client)
    room = make_room(client)["room_id"]
    signup(client)
    assert client.post(f"/api/rooms/{room}/leave").status_code == 404
    client.cookies.clear()
    assert client.post(f"/api/rooms/{room}/leave").status_code == 401


def test_departed_family_heart_has_no_name(client):
    room = setup_elder(client)["room_id"]
    diary = _diary(room, "ELDER")
    token = client.post(f"/api/rooms/{room}/invites", json={"kind": "FAMILY"}).json()["url"].split("#")[1]
    signup(client)
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "CHILD"}).status_code == 200
    assert client.post(f"/api/diaries/{diary}/reaction", json={"kind": "HEART", "on": True}).status_code == 200
    assert client.post(f"/api/rooms/{room}/leave").status_code == 200
    result = client.get("/api/elder/family-news")
    assert result.status_code == 200
    assert result.json()["hearts"][0]["name"] is None
