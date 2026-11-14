"""가족방 구성원 목록 — 구성원이면 누구나 보고, 내보낸 사람·남에게는 안 보인다."""

from tests.conftest import make_room, signup

KEYS = {"user_id", "name", "nickname", "relation_tag", "joined_at", "is_owner"}


def login(client, who):
    assert client.post("/api/auth/login", json={"email": who["email"], "password": "test1234"}).status_code == 200


def join(client, room_id):
    """방장으로 로그인된 상태에서 초대 링크를 만들고, 새 계정이 손주로 들어온다. 끝나면 손주로 로그인돼 있다."""
    token = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"}).json()["url"].split("#", 1)[1]
    member = signup(client)
    body = {"token": token, "relation_tag": "GRANDCHILD", "name": "손주", "nickname": "막내"}
    assert client.post("/api/invites/accept", json=body).status_code == 200
    return member


def test_owner_alone(client):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    response = client.get(f"/api/rooms/{room_id}/members")
    assert response.status_code == 200
    (only,) = response.json()
    assert set(only) == KEYS  # 다른 가족에게 보이는 목록 — email 이 없다
    assert (only["user_id"], only["name"], only["nickname"]) == (owner["user_id"], "테스터", None)
    assert (only["relation_tag"], only["is_owner"]) == ("CHILD", True)


def test_any_member_sees_everyone_in_join_order(client):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    member = join(client, room_id)
    response = client.get(f"/api/rooms/{room_id}/members")  # 방장이 아닌 손주가 부른다
    assert response.status_code == 200
    first, second = response.json()
    assert (first["user_id"], first["is_owner"]) == (owner["user_id"], True)
    assert set(second) == KEYS
    assert (second["user_id"], second["name"], second["nickname"]) == (member["user_id"], "손주", "막내")
    assert (second["relation_tag"], second["is_owner"]) == ("GRANDCHILD", False)


def test_removed_member_is_hidden_and_locked_out(client):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    member = join(client, room_id)
    login(client, owner)
    assert client.delete(f"/api/rooms/{room_id}/members/{member['user_id']}").status_code == 200
    assert [m["user_id"] for m in client.get(f"/api/rooms/{room_id}/members").json()] == [owner["user_id"]]
    login(client, member)
    response = client.get(f"/api/rooms/{room_id}/members")
    assert response.status_code == 404
    assert response.json()["code"] == "ROOM_NOT_FOUND"


def test_outsider_missing_room_and_logged_out(client):
    signup(client)
    room_id = make_room(client)["room_id"]
    signup(client)  # 구성원이 아닌 계정
    for path in (f"/api/rooms/{room_id}/members", f"/api/rooms/{room_id + 999}/members"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["code"] == "ROOM_NOT_FOUND"
    client.cookies.clear()
    assert client.get(f"/api/rooms/{room_id}/members").status_code == 401
