"""가족 한마디 (11/19 — D50 '글 답장은 없다'를 바꿈): 어르신 일기에 한 사람 1개, 이모지 칸과 따로.

어르신께는 가족 소식 첫 장(hearts)으로 같이 내려가 한 번 읽어 드리고, 글을 바꾸면 다시 읽어 드린다.
+ 새 소식이 없을 때 '지난 소식 다시 듣기'(GET /elder/family-news?again=1).
"""

import pytest

from app.db import SessionLocal
from app.models import Diary
from tests.conftest import setup_elder
from tests.test_reactions import _diary, _heard, _home_count, _join, _news, _react, _stored


def _reply(client, diary_id, text):
    return client.post(f"/api/diaries/{diary_id}/reply", json={"text": text})


def _unreply(client, diary_id):
    return client.delete(f"/api/diaries/{diary_id}/reply")


def _kinds(response):
    return [r["kind"] for r in response.json()["reactions"]]


# ---------------------------------------------------------------- 남기기 · 바꾸기 · 지우기
def test_reply_send_change_delete(client):
    room_id = setup_elder(client)["room_id"]
    diary_id, me = _diary(room_id), client.get("/api/auth/me").json()["user_id"]
    r = _reply(client, diary_id, "보고 싶어요")
    assert r.status_code == 200, r.text
    (reply,) = r.json()["reactions"]
    assert (reply["by"], reply["user_id"], reply["kind"], reply["name"]) == ("FAMILY", me, "REPLY", "테스터")
    assert reply["text"] == "보고 싶어요"
    assert set(_stored(diary_id)[0]) == {"by", "user_id", "kind", "text", "at"}  # 이름은 DB 에 넣지 않는다
    assert _reply(client, diary_id, "보고 싶어요").json()["reactions"] == [reply]  # 같은 글 다시 — at 도 그대로
    (changed,) = _reply(client, diary_id, "곧 갈게요").json()["reactions"]  # 바꿔 끼움 — 한 사람 1개
    assert changed["text"] == "곧 갈게요"
    assert changed["at"] != reply["at"]
    assert client.get(f"/api/diaries/{diary_id}").json()["reactions"] == [changed]
    assert _unreply(client, diary_id).status_code == 204
    assert _stored(diary_id) == []
    assert _unreply(client, diary_id).status_code == 204  # 없어도 204


def test_reply_becomes_one_line_of_40(client):
    diary_id = _diary(setup_elder(client)["room_id"])
    r = _reply(client, diary_id, "  엄마\n김치\t최고\x00\x7f  ")  # 줄바꿈·제어 문자는 빈칸으로, 앞뒤 빈칸은 뗀다
    assert r.status_code == 200, r.text
    assert r.json()["reactions"][0]["text"] == "엄마 김치 최고"
    r = _reply(client, diary_id, " " + "가" * 40 + "\n")  # 빈칸을 뗀 뒤 40자
    assert r.status_code == 200, r.text
    assert r.json()["reactions"][0]["text"] == "가" * 40


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "\x00", "가" * 41, None, 3])
def test_bad_reply_text_is_422(client, text):
    diary_id = _diary(setup_elder(client)["room_id"])
    r = _reply(client, diary_id, text)
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION"
    assert client.post(f"/api/diaries/{diary_id}/reply", json={}).status_code == 422
    assert _stored(diary_id) == []


def test_reply_only_in_my_room_and_not_on_my_own_diary(client):
    room_id = setup_elder(client)["room_id"]
    elder_diary, family_diary = _diary(room_id), _diary(room_id, "FAMILY")
    r = _reply(client, family_diary, "잘 읽었어요")  # 내가 쓴 가족 일기에는 못 남긴다 (D98)
    assert (r.status_code, r.json()["code"]) == (400, "REPLY_NOT_ALLOWED")
    assert _unreply(client, family_diary).status_code == 204  # 지울 것이 없을 뿐
    gone = _diary(room_id, status="DELETED")
    assert _reply(client, elder_diary, "사랑해요").status_code == 200
    mine = _stored(elder_diary)

    setup_elder(client)  # 다른 가족·다른 방
    responses = [
        _reply(client, elder_diary, "보고 싶어요"),
        _reply(client, family_diary, "보고 싶어요"),  # 남의 가족방 — 방향 검사(400)보다 먼저 404
        _unreply(client, elder_diary),
        _reply(client, gone, "보고 싶어요"),
        _reply(client, 999999, "보고 싶어요"),
        _unreply(client, 999999),
    ]
    for r in responses:
        assert r.status_code == 404
        assert r.json()["code"] == "DIARY_NOT_FOUND"
    assert _stored(elder_diary) == mine  # 남의 방 한마디는 그대로
    assert _stored(family_diary) == []


def test_reply_needs_family_cookie(client):
    diary_id = _diary(setup_elder(client)["room_id"])
    client.cookies.delete("session")  # 기기 쿠키만 남긴다
    assert _reply(client, diary_id, "보고 싶어요").status_code == 401
    assert _unreply(client, diary_id).status_code == 401
    assert _stored(diary_id) == []


# ---------------------------------------------------------------- 이모지 칸과 따로
def test_emoji_and_reply_do_not_touch_each_other(client):
    diary_id = _diary(setup_elder(client)["room_id"])
    assert _kinds(_reply(client, diary_id, "사랑해요")) == ["REPLY"]
    # 응답에서 한마디는 이모지 뒤 — 가족 홈이 '내 칸'을 앞에서부터 찾는다. DB 에는 받은 순서 그대로
    assert _kinds(_react(client, diary_id, "HEART")) == ["HEART", "REPLY"]  # 켜기 — 한마디는 남는다
    assert [r["kind"] for r in _stored(diary_id)] == ["REPLY", "HEART"]
    assert _kinds(_react(client, diary_id, "CLAP")) == ["CLAP", "REPLY"]  # 바꾸기
    assert _kinds(_react(client, diary_id, "CLAP", on=False)) == ["REPLY"]  # 끄기
    assert _kinds(_react(client, diary_id, "SMILE", on=False)) == ["REPLY"]  # 안 켠 이모지 끄기 — 한마디는 그대로
    assert client.post(f"/api/diaries/{diary_id}/reaction", json={"kind": "REPLY", "on": False}).status_code == 422
    _react(client, diary_id, "SMILE")
    assert _kinds(_reply(client, diary_id, "곧 갈게요")) == ["SMILE", "REPLY"]  # 한마디를 바꿔도 이모지는 남는다
    assert _unreply(client, diary_id).status_code == 204
    assert [r["kind"] for r in _stored(diary_id)] == ["SMILE"]  # 한마디만 지워진다


def test_reply_is_per_person_and_not_counted_as_emoji(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id)
    _react(client, diary_id, "HEART")
    _reply(client, diary_id, "잘 읽었어요")
    _join(client, room_id)  # 여기부터 손주
    reactions = _reply(client, diary_id, "할머니 최고").json()["reactions"]
    assert [(r["name"], r["kind"], r.get("text")) for r in reactions] == [
        ("테스터", "HEART", None),
        ("테스터", "REPLY", "잘 읽었어요"),
        ("손주", "REPLY", "할머니 최고"),
    ]
    assert "text" not in reactions[0]  # 이모지 칸은 text 키를 싣지 않는다
    # 가족 화면은 이모지를 kind 로 센다 — 한마디 2개가 있어도 하트는 1개
    assert {kind: sum(r["kind"] == kind for r in reactions) for kind in ("HEART", "SMILE", "CLAP")} == {
        "HEART": 1,
        "SMILE": 0,
        "CLAP": 0,
    }
    assert _unreply(client, diary_id).status_code == 204  # 내 것(손주)만 지운다
    assert [(r["kind"], r.get("text")) for r in _stored(diary_id)] == [("HEART", None), ("REPLY", "잘 읽었어요")]


def test_reply_on_family_diary_stays_between_family(client):
    """가족 일기에 다른 가족이 한마디 (D98). 가족 화면에는 보이고, 어르신 가족 소식에는 나오지 않는다."""
    room_id = setup_elder(client)["room_id"]
    family_diary = _diary(room_id, "FAMILY")  # 방장(테스터)이 쓴 일기
    _join(client, room_id)  # 여기부터 손주
    r = _reply(client, family_diary, "엄마 사진 좋아요")
    assert r.status_code == 200, r.text
    (reply,) = r.json()["reactions"]
    assert (reply["by"], reply["kind"], reply["name"], reply["text"]) == ("FAMILY", "REPLY", "손주", "엄마 사진 좋아요")
    r = _react(client, family_diary, "HEART")  # 가족 일기 이모지는 그대로 막혀 있다
    assert (r.status_code, r.json()["code"]) == (409, "REACTION_NOT_ALLOWED")

    news = _news(client)  # 어르신 기기: 일기는 나오지만 가족끼리 한마디는 빠진다
    assert [d["diary_id"] for d in news["diaries"]] == [family_diary]
    assert news["diaries"][0]["reactions"] == []
    assert news["hearts"] == []
    assert _home_count(client) == 1  # 안 들은 가족 일기 1건뿐 — 한마디로 늘지 않는다
    r = client.post(f"/api/elder/diaries/{family_diary}/like", json={"on": True})  # 어르신 응답에도 빠진다
    assert [(c["by"], c["kind"]) for c in r.json()["reactions"]] == [("ELDER", "LIKE")]
    assert [c["kind"] for c in client.get(f"/api/diaries/{family_diary}").json()["reactions"]] == ["LIKE", "REPLY"]
    assert _unreply(client, family_diary).status_code == 204
    assert [c["by"] for c in _stored(family_diary)] == ["ELDER"]


# ---------------------------------------------------------------- 어르신 가족 소식 첫 장
def test_unheard_reply_is_read_once_and_again_when_changed(client):
    diary_id = _diary(setup_elder(client)["room_id"])
    at = _reply(client, diary_id, "엄마 김치 최고").json()["reactions"][0]["at"]
    hearts = _news(client)["hearts"]
    on = {
        "diary_body": "오늘 공원을 걸었어요.",
        "diary_posted_at": hearts[0]["diary_posted_at"],
        "diary_thumb_url": None,
    }
    assert hearts == [
        {"diary_id": diary_id, "kind": "REPLY", "name": "테스터", "at": at, "text": "엄마 김치 최고"} | on
    ]
    assert _home_count(client) == 1  # 한마디만 와도 소식 1건
    heart_at = _react(client, diary_id, "HEART").json()["reactions"][0]["at"]
    hearts = _news(client)["hearts"]  # 이모지와 한마디가 같은 자리에서, 받은 순서로
    assert [(h["kind"], h.get("text")) for h in hearts] == [("REPLY", "엄마 김치 최고"), ("HEART", None)]
    assert "text" not in hearts[1]
    assert _home_count(client) == 1  # 몇 개든 1건

    assert _heard(client, heart_at).status_code == 204
    assert _news(client)["hearts"] == []
    assert _home_count(client) == 0
    assert all("heard_at" in cell for cell in _stored(diary_id))
    assert len(client.get(f"/api/diaries/{diary_id}").json()["reactions"]) == 2  # 가족 화면에는 그대로 보인다

    assert _reply(client, diary_id, "엄마 김치 최고").status_code == 200  # 같은 글 다시 — 들은 칸 그대로
    assert _news(client)["hearts"] == []
    _reply(client, diary_id, "또 먹고 싶어요")  # 글을 바꾸면 새 칸 — 다시 읽어 드린다
    (again,) = _news(client)["hearts"]
    assert (again["kind"], again["name"], again["text"]) == ("REPLY", "테스터", "또 먹고 싶어요")
    assert _unreply(client, diary_id).status_code == 204  # 지우면 사라진다
    assert _news(client)["hearts"] == []


def test_reply_that_came_later_waits(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id)
    first = _reply(client, diary_id, "잘 읽었어요").json()["reactions"][0]["at"]
    _join(client, room_id)
    _reply(client, diary_id, "할머니 최고")  # 어르신이 첫 장을 듣는 사이에 온 것
    assert _heard(client, first).status_code == 204
    (later,) = _news(client)["hearts"]  # until 뒤에 온 것은 다음에 읽어 드린다
    assert (later["name"], later["text"]) == ("손주", "할머니 최고")


def test_hearts_limit_counts_emoji_and_reply_together(client, monkeypatch):
    from app.routers import diaries

    monkeypatch.setattr(diaries, "ELDER_HEARTS_LIMIT", 1)
    diary_id = _diary(setup_elder(client)["room_id"])
    _react(client, diary_id, "HEART")
    _reply(client, diary_id, "사랑해요")
    (first,) = _news(client)["hearts"]
    assert first["kind"] == "HEART"
    assert _heard(client, first["at"]).status_code == 204
    (second,) = _news(client)["hearts"]  # 넘친 것은 들은 뒤에 나온다
    assert (second["kind"], second["text"]) == ("REPLY", "사랑해요")


def test_reply_stays_in_its_room(client):
    diary_id = _diary(setup_elder(client)["room_id"])
    at = _reply(client, diary_id, "보고 싶어요").json()["reactions"][0]["at"]
    setup_elder(client)  # 다른 가족방의 기기
    assert _news(client)["hearts"] == []
    assert _home_count(client) == 0
    assert _heard(client, at).status_code == 204
    assert "heard_at" not in _stored(diary_id)[0]  # 남의 방 한마디에는 손대지 않는다


# ---------------------------------------------------------------- 지난 소식 다시 듣기 (again=1)
def _read_marks(diary_ids):
    with SessionLocal() as db:
        return {diary_id: db.get(Diary, diary_id).elder_read_at for diary_id in diary_ids}


def test_again_gives_five_recent_heard_family_diaries_and_keeps_read_marks(client):
    room_id = setup_elder(client)["room_id"]
    path = "/api/elder/family-news"
    assert client.get(path, params={"again": 1}).json() == {"diaries": [], "hearts": [], "has_more": False}
    heard = [_diary(room_id, "FAMILY") for _ in range(6)]
    gone = _diary(room_id, "FAMILY")
    for diary_id in [*heard, gone]:
        assert client.post(f"/api/elder/diaries/{diary_id}/read").status_code == 204
    assert client.delete(f"/api/diaries/{gone}").status_code == 204  # 들은 뒤 가족이 지운 일기
    unheard = _diary(room_id, "FAMILY")
    _react(client, _diary(room_id), "HEART")  # 어르신 일기 + 못 들은 하트
    marks = _read_marks([*heard, unheard])

    again = client.get(path, params={"again": 1})
    assert again.status_code == 200, again.text
    # 들은 가족 일기만, 최근에 올라온 5개를 최신 먼저 — 안 들은 일기·어르신 일기·지운 일기는 없다
    assert [d["diary_id"] for d in again.json()["diaries"]] == heard[:0:-1]
    assert again.json()["hearts"] == []  # 첫 장(하트·한마디)은 다시 듣기에 없다
    assert {d["read_by_elder"] for d in again.json()["diaries"]} == {True}

    assert _read_marks([*heard, unheard]) == marks  # 다시 듣기는 읽음 표시를 바꾸지 않는다
    news = _news(client)
    assert [d["diary_id"] for d in news["diaries"]] == [unheard]  # 평소 목록은 그대로
    assert len(news["hearts"]) == 1
    assert _home_count(client) == 2

    setup_elder(client)  # 다른 가족방의 기기에는 안 보인다
    assert client.get(path, params={"again": 1}).json()["diaries"] == []
