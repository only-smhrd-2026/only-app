"""일기 리액션 (D54·D63) — 가족 이모지·어르신 좋아요는 '이 상태로' 방식, 못 들은 하트는 가족 소식 첫 장과 홈 숫자에."""

import uuid

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Diary, FamilyRoom, RoomMember
from tests.conftest import setup_elder, signup


def _diary(room_id, author_type="ELDER", status="POSTED"):
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


def _stored(diary_id):
    with SessionLocal() as db:
        return db.get(Diary, diary_id).reactions


def _react(client, diary_id, kind, on=True):
    return client.post(f"/api/diaries/{diary_id}/reaction", json={"kind": kind, "on": on})


def _like(client, diary_id, on=True):
    return client.post(f"/api/elder/diaries/{diary_id}/like", json={"on": on})


def _join(client, room_id):
    """방장으로 로그인된 상태에서 초대 링크를 만들고 새 계정 '손주'가 들어온다. 끝나면 손주로 로그인돼 있다."""
    token = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"}).json()["url"].split("#", 1)[1]
    signup(client)
    body = {"token": token, "relation_tag": "GRANDCHILD", "name": "손주"}
    assert client.post("/api/invites/accept", json=body).status_code == 200


def _news(client):
    return client.get("/api/elder/family-news").json()


def _home_count(client):
    return client.get("/api/elder/home").json()["unread_family_news"]


def _heard(client, until):
    return client.post("/api/elder/hearts/heard", json={"until": until})


# ---------------------------------------------------------------- 가족 이모지 · 어르신 좋아요 (D54)
def test_family_reaction_on_swap_off(client):
    room_id = setup_elder(client)["room_id"]
    diary_id, me = _diary(room_id), client.get("/api/auth/me").json()["user_id"]
    r = _react(client, diary_id, "HEART")
    assert r.status_code == 200, r.text
    (heart,) = r.json()["reactions"]
    assert (heart["by"], heart["user_id"], heart["kind"], heart["name"]) == ("FAMILY", me, "HEART", "테스터")
    assert _react(client, diary_id, "HEART").json()["reactions"] == [heart]  # 같은 것 다시 켜기 — at 도 그대로
    (clap,) = _react(client, diary_id, "CLAP").json()["reactions"]  # 다른 것으로 바꿔 끼움
    assert clap["kind"] == "CLAP"
    assert _react(client, diary_id, "HEART", on=False).json()["reactions"] == [clap]  # 다른 것 끄기 — 그대로
    assert _react(client, diary_id, "CLAP", on=False).json()["reactions"] == []
    assert _react(client, diary_id, "CLAP", on=False).json()["reactions"] == []  # 한 번 더 — 그대로


def test_name_is_nickname_and_only_in_response(client):
    room_id = setup_elder(client)["room_id"]
    diary_id, me = _diary(room_id), client.get("/api/auth/me").json()["user_id"]
    with SessionLocal() as db:
        db.scalar(select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == me)).nickname = "큰딸"
        db.commit()
    assert _react(client, diary_id, "HEART").json()["reactions"][0]["name"] == "큰딸"
    _join(client, room_id)
    first, second = _react(client, diary_id, "SMILE").json()["reactions"]
    assert (first["name"], first["kind"]) == ("큰딸", "HEART")  # 앞사람 칸은 그대로
    assert (second["name"], second["kind"]) == ("손주", "SMILE")
    assert all("name" not in stored for stored in _stored(diary_id))  # 이름은 DB 에 넣지 않는다


def test_elder_like_on_off(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id, "FAMILY")
    r = _like(client, diary_id)
    assert r.status_code == 200, r.text
    (like,) = r.json()["reactions"]
    assert (like["by"], like["kind"], like["user_id"], like["name"]) == ("ELDER", "LIKE", None, None)
    assert set(_stored(diary_id)[0]) == {"by", "kind", "at"}  # 어르신 칸에는 user_id 키가 없다
    assert _like(client, diary_id).json()["reactions"] == [like]
    assert _like(client, diary_id, on=False).json()["reactions"] == []
    assert _like(client, diary_id, on=False).json()["reactions"] == []


def test_wrong_direction_is_409(client):
    room_id = setup_elder(client)["room_id"]
    family_diary, elder_diary = _diary(room_id, "FAMILY"), _diary(room_id)
    for r in (_react(client, family_diary, "HEART"), _like(client, elder_diary)):
        assert r.status_code == 409
        assert r.json()["code"] == "REACTION_NOT_ALLOWED"
    assert _stored(family_diary) == []
    assert _stored(elder_diary) == []


def test_other_room_missing_and_deleted_are_404(client):
    room_id = setup_elder(client)["room_id"]
    elder_diary, family_diary = _diary(room_id), _diary(room_id, "FAMILY")
    other_room = setup_elder(client)["room_id"]  # 새 가족·새 방·새 기기 쿠키
    gone_elder, gone_family = _diary(other_room, status="DELETED"), _diary(other_room, "FAMILY", status="DELETED")
    responses = [
        _react(client, elder_diary, "HEART"),  # 남의 가족방 — 방향 검사(409)보다 먼저 404
        _like(client, family_diary),
        _react(client, family_diary, "HEART"),
        _react(client, 999999, "HEART"),
        _like(client, 999999),
        _react(client, gone_elder, "HEART"),
        _like(client, gone_family),
    ]
    for r in responses:
        assert r.status_code == 404
        assert r.json()["code"] == "DIARY_NOT_FOUND"
    assert _stored(elder_diary) == []


@pytest.mark.parametrize("body", [{"kind": "LIKE", "on": True}, {"kind": "ANGRY", "on": True}, {"kind": "HEART"}])
def test_bad_reaction_body_is_422(client, body):
    room_id = setup_elder(client)["room_id"]
    assert client.post(f"/api/diaries/{_diary(room_id)}/reaction", json=body).status_code == 422


def test_each_side_needs_its_own_cookie(client):
    signup(client)  # 가족 쿠키만
    r = _like(client, 1)
    assert r.status_code == 401
    assert r.json()["code"] == "DEVICE_REQUIRED"
    assert _heard(client, "2026-11-14T10:00:00+09:00").status_code == 401
    diary_id = _diary(setup_elder(client)["room_id"])
    client.cookies.delete("session")  # 기기 쿠키만 남긴다
    assert _react(client, diary_id, "HEART").status_code == 401


def test_reactions_ride_on_every_diary_list(client):
    room_id = setup_elder(client)["room_id"]
    elder_diary, family_diary = _diary(room_id), _diary(room_id, "FAMILY")
    _react(client, elder_diary, "HEART")
    _like(client, family_diary)
    listed = {d["diary_id"]: d["reactions"] for d in client.get(f"/api/rooms/{room_id}/diaries").json()["diaries"]}
    assert (listed[elder_diary][0]["kind"], listed[elder_diary][0]["name"]) == ("HEART", "테스터")
    assert listed[family_diary][0]["kind"] == "LIKE"
    assert _news(client)["diaries"][0]["reactions"][0]["kind"] == "LIKE"
    assert client.get(f"/api/diaries/{elder_diary}").json()["reactions"][0]["kind"] == "HEART"


# ---------------------------------------------------------------- 하트가 왔어요 (D63)
def test_unheard_hearts_in_family_news_and_home_count(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id)
    assert _news(client) == {"diaries": [], "hearts": []}
    assert _home_count(client) == 0
    at = _react(client, diary_id, "HEART").json()["reactions"][0]["at"]
    assert _news(client)["hearts"] == [{"diary_id": diary_id, "kind": "HEART", "name": "테스터", "at": at}]
    assert _home_count(client) == 1  # 가족 일기가 없어도 하트가 오면 소식 1건
    _diary(room_id, "FAMILY")
    assert _home_count(client) == 2  # 안 들은 가족 일기 1 + 하트 1건(몇 개든)

    assert _heard(client, at).status_code == 204
    assert _news(client)["hearts"] == []
    assert _home_count(client) == 1
    heard_at = _stored(diary_id)[0]["heard_at"]
    assert _heard(client, at).status_code == 204
    assert _stored(diary_id)[0]["heard_at"] == heard_at  # 다시 불러도 처음 들은 시각 그대로
    assert len(client.get(f"/api/diaries/{diary_id}").json()["reactions"]) == 1  # 가족 화면에는 그대로 보인다


def test_heart_that_came_later_waits_and_swapped_emoji_is_new(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id)
    first = _react(client, diary_id, "HEART").json()["reactions"][0]["at"]
    _join(client, room_id)
    _react(client, diary_id, "SMILE")  # 어르신이 첫 장을 듣는 사이에 온 것
    assert [(h["name"], h["kind"]) for h in _news(client)["hearts"]] == [("테스터", "HEART"), ("손주", "SMILE")]
    assert _heard(client, first).status_code == 204
    (later,) = _news(client)["hearts"]  # until 뒤에 온 것은 다음에 읽어 드린다
    assert (later["name"], later["kind"]) == ("손주", "SMILE")
    assert _heard(client, later["at"]).status_code == 204
    assert _news(client)["hearts"] == []
    _react(client, diary_id, "CLAP")  # 들은 뒤 이모지를 바꾸면 새 칸 — 다시 알려 드린다
    assert [(h["name"], h["kind"]) for h in _news(client)["hearts"]] == [("손주", "CLAP")]
    _react(client, diary_id, "CLAP", on=False)  # 취소하면 사라진다
    assert _news(client)["hearts"] == []


def test_hearts_stay_in_their_room(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id)
    at = _react(client, diary_id, "HEART").json()["reactions"][0]["at"]
    setup_elder(client)  # 다른 가족방의 기기
    assert _news(client)["hearts"] == []
    assert _home_count(client) == 0
    assert _heard(client, at).status_code == 204
    assert "heard_at" not in _stored(diary_id)[0]  # 남의 방 하트에는 손대지 않는다
    assert _heard(client, "2026-11-14T10:00:00").status_code == 422  # 시간대 없는 시각은 받지 않는다
