"""내 정보 (11/27): 이름 고치기 · 프로필 사진 올리기·바꾸기·지우기 · 사진은 같은 가족방 사람에게만 보인다."""

import io

from PIL import Image

from tests.conftest import add_photos, connect_device, make_room, setup_elder, signup
from tests.test_member_nickname import login
from tests.test_room_settings import family as family


def _jpeg(size=(1200, 800)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, "JPEG")
    return out.getvalue()


def _put(client, data=None):
    return client.put("/api/auth/me/photo", files={"file": ("me.jpg", data or _jpeg(), "image/jpeg")})


def test_change_name(client):
    signup(client)
    response = client.patch("/api/auth/me", json={"name": "  김가족  "})
    assert response.status_code == 200 and response.json()["name"] == "김가족"
    assert client.get("/api/auth/me").json()["name"] == "김가족"
    assert client.patch("/api/auth/me", json={"name": "   "}).status_code == 422
    assert client.patch("/api/auth/me", json={"name": "가" * 31}).status_code == 422
    client.cookies.clear()
    assert client.patch("/api/auth/me", json={"name": "누구"}).status_code == 401


def test_profile_photo_put_replace_delete(client):
    signup(client)
    assert client.get("/api/auth/me").json()["profile_url"] is None
    first = _put(client)
    assert first.status_code == 200, first.text
    url = first.json()["profile_url"]
    assert url.startswith("/api/media/users/")
    pic = client.get(url)
    assert pic.status_code == 200
    assert max(Image.open(io.BytesIO(pic.content)).size) == 400  # 작게 줄여 저장
    second = _put(client).json()["profile_url"]
    assert second != url
    assert client.get(url).status_code == 404  # 옛 사진은 지워짐
    assert client.delete("/api/auth/me/photo").json()["profile_url"] is None
    assert client.get(second).status_code == 404
    assert _put(client, b"not an image").json()["code"] == "BAD_IMAGE"


def test_profile_photo_visible_only_to_room(client, family):
    owner, member, room_id, _ = family  # 지금 로그인 = member
    url = _put(client).json()["profile_url"]
    login(client, owner)
    rows = client.get(f"/api/rooms/{room_id}/members").json()
    assert next(m for m in rows if m["user_id"] == member["user_id"])["profile_url"] == url
    assert client.get(url).status_code == 200  # 같은 가족방
    add_photos(room_id)  # 기기 연결은 사진 3장부터
    connect_device(client, room_id)
    client.cookies.delete("session")  # 어르신 기기 쿠키만 (같은 방)
    assert client.get(url).status_code == 200
    client.cookies.clear()
    signup(client)
    make_room(client)
    response = client.get(url)  # 다른 가족방 사람 — 있는지도 모르게 404
    assert response.status_code == 404 and response.json()["code"] == "MEDIA_NOT_FOUND"


def test_elder_photo_owner_only_and_room_only(client, family):
    owner, _member, room_id, _ = family  # 지금 로그인 = member
    path = f"/api/rooms/{room_id}/elder-photo"
    put = lambda: client.put(path, files={"file": ("elder.jpg", _jpeg(), "image/jpeg")})  # noqa: E731
    assert put().status_code in (403, 404)  # 방장이 아니면 못 넣음
    assert client.get("/api/rooms").json()[0]["elder_photo_url"] is None
    login(client, owner)
    first = put()
    assert first.status_code == 200, first.text
    url = first.json()["elder_photo_url"]
    assert url.startswith(f"/api/media/rooms/{room_id}/elder/")
    assert max(Image.open(io.BytesIO(client.get(url).content)).size) == 400
    second = put().json()["elder_photo_url"]
    assert client.get(url).status_code == 404  # 옛 사진은 지워짐
    add_photos(room_id)
    connect_device(client, room_id)
    client.cookies.delete("session")  # 어르신 기기도 볼 수 있다 (같은 방)
    assert client.get(second).status_code == 200
    client.cookies.clear()
    signup(client)
    make_room(client)
    assert client.get(second).status_code == 404  # 다른 가족방 사람
    login(client, owner)
    assert client.delete(path).json()["elder_photo_url"] is None
    assert client.get(second).status_code == 404


def test_profile_photo_on_feed_and_replies(client):
    """11/27: 내 정보에서 올린 사진이 가족 화면 일기 카드(쓴 사람)·댓글 칸에 붙는다. 어르신 기기 응답엔 없다."""
    from tests.test_family_diary import _post
    from tests.test_reactions import _diary

    room_id = setup_elder(client)["room_id"]
    url = _put(client).json()["profile_url"]
    mine = _post(client, room_id).json()
    assert mine["author_profile_url"] == url
    elder_diary = _diary(room_id)
    (reply,) = client.post(f"/api/diaries/{elder_diary}/reply", json={"text": "보고 싶어요"}).json()["reactions"]
    assert reply["profile_url"] == url
    feed = {d["diary_id"]: d for d in client.get(f"/api/rooms/{room_id}/diaries").json()["diaries"]}
    assert feed[mine["diary_id"]]["author_profile_url"] == url
    assert feed[elder_diary]["author_profile_url"] is None  # 어르신 일기는 방의 elder_photo_url
    client.cookies.delete("session")  # 어르신 기기 쿠키만
    (elder_view,) = client.get("/api/elder/diaries").json()["diaries"]
    assert "profile_url" not in elder_view["reactions"][0]
    news = client.get("/api/elder/family-news").json()["diaries"]
    assert all(d["author_profile_url"] is None for d in news)


def test_profile_photo_on_memory_comments(client):
    """회상 카드 댓글 칸에도 프로필 사진 (11/27)."""
    from tests.test_memory_cards import _run, _talk

    e = setup_elder(client)
    url = _put(client).json()["profile_url"]
    sid = _talk(e["room_id"], e["photo_ids"][0])
    _run()
    (reply,) = client.post(f"/api/memories/{sid}/reply", json={"text": "보고 싶어요"}).json()["reactions"]
    assert reply["profile_url"] == url
