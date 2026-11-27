"""다른 분 호칭은 방장만, 내 호칭은 나도 바꿀 수 있다 (11/27 내 정보)."""

from tests.test_room_settings import family as family


def login(client, user):
    assert client.post("/api/auth/login", json={"email": user["email"], "password": "test1234"}).status_code == 200


def test_owner_changes_nickname_and_clears_it(client, family):
    owner, member, room, _ = family
    login(client, owner)
    path = f"/api/rooms/{room}/members/{member['user_id']}"
    response = client.patch(path, json={"nickname": "  큰딸  "})
    assert response.status_code == 200
    assert response.json()["nickname"] == "큰딸"
    rows = client.get(f"/api/rooms/{room}/members").json()
    assert next(m for m in rows if m["user_id"] == member["user_id"])["nickname"] == "큰딸"
    assert client.patch(path, json={"nickname": "  "}).json()["nickname"] is None
    assert client.patch(path, json={"nickname": "가" * 13}).status_code == 422
    own = client.patch(f"/api/rooms/{room}/members/{owner['user_id']}", json={"nickname": "큰아들"})
    assert own.status_code == 200 and own.json()["is_owner"] is True


def test_nickname_permissions_and_removed_member(client, family):
    owner, member, room, _ = family
    path = f"/api/rooms/{room}/members/{member['user_id']}"
    assert client.patch(f"/api/rooms/{room}/members/{owner['user_id']}", json={"nickname": "딸"}).status_code == 403
    mine = client.patch(path, json={"nickname": "막내"})  # 내 호칭은 방장이 아니어도
    assert mine.status_code == 200 and mine.json()["nickname"] == "막내"
    login(client, owner)
    assert client.delete(path).status_code == 200
    response = client.patch(path, json={"nickname": "딸"})
    assert response.status_code == 404 and response.json()["code"] == "MEMBER_NOT_FOUND"
    assert client.patch(f"/api/rooms/{room}/members/99999999", json={"nickname": None}).status_code == 404
    client.cookies.clear()
    assert client.patch(path, json={"nickname": "딸"}).status_code == 401
