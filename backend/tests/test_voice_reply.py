"""가족 목소리 답장 (D99, 11/24) — 저장·어르신 가족 소식·바꾸기/지우기/탈퇴 때 소리 파일 지우기·권한.

ffmpeg 는 부르지 않는다(stt.to_mp3 를 바꿔 끼움). 받아 적기는 conftest 의 mock.
"""

import pytest

from app.ai import stt
from app.config import VOICE_REPLY_KBPS
from app.services import storage
from tests.conftest import setup_elder, signup
from tests.test_reactions import _diary, _join, _stored

AUDIO = {"audio": ("voice.webm", b"fake-webm", "audio/webm")}


@pytest.fixture(autouse=True)
def fake_mp3(monkeypatch):
    """12초짜리 mp3 인 척 — 고정 비트레이트라 길이는 바이트로 정해진다."""
    monkeypatch.setattr(stt, "to_mp3", lambda audio, sec, kbps: b"\xff" * (VOICE_REPLY_KBPS * 125 * 12))


def _voice(client, diary_id):
    return client.post(f"/api/diaries/{diary_id}/voice-reply", files=AUDIO)


def _key(cell):
    return cell["audio_url"].removeprefix("/api/media/")


def test_voice_reply_is_kept_and_played_to_elder(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id)
    r = _voice(client, diary_id)
    assert r.status_code == 200, r.text
    (cell,) = [c for c in r.json()["reactions"] if c["kind"] == "REPLY"]
    assert cell["audio_sec"] == 12 and cell["text"]  # 자막(mock 받아 적기)
    assert cell["audio_url"].startswith(f"/api/media/rooms/{room_id}/voice/")
    media = client.get(cell["audio_url"])
    assert media.status_code == 200 and media.headers["content-type"] == "audio/mpeg"
    (heart,) = client.get("/api/elder/family-news").json()["hearts"]  # 어르신 가족 소식에 한 장
    assert (heart["kind"], heart["audio_url"], heart["audio_sec"]) == ("REPLY", cell["audio_url"], 12)
    assert "audio_url" not in _stored(diary_id)[0]  # DB 에는 key 만, 주소는 응답에만


def test_voice_reply_keeps_preview_caption_without_transcribing_again(client, monkeypatch):
    diary_id = _diary(setup_elder(client)["room_id"])
    monkeypatch.setattr(stt, "transcribe", lambda *_: pytest.fail("이미 확인한 자막을 다시 받아쓰면 안 된다"))
    path = f"/api/diaries/{diary_id}/voice-reply"
    result = client.post(path, files=AUDIO, data={"caption": "할머니  오늘도 즐거웠어요."})
    assert result.status_code == 200, result.text
    assert result.json()["reactions"][0]["text"] == "할머니 오늘도 즐거웠어요."
    assert client.post(path, files=AUDIO, data={"caption": "가" * 201}).status_code == 422


def test_new_reply_keeps_old_sound_and_delete_removes_it(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id)
    one = _voice(client, diary_id).json()["reactions"][0]
    two = _voice(client, diary_id).json()["reactions"][1]  # 또 녹음 → 칸이 하나 더 (11/25 여러 개)
    assert len(_stored(diary_id)) == 2 and storage.get(_key(one)) and storage.get(_key(two))
    client.post(f"/api/diaries/{diary_id}/reply", json={"text": "보고 싶어요"})  # 글 한마디도 더함 — 소리는 그대로
    assert len(_stored(diary_id)) == 3 and storage.get(_key(two))
    edit = client.patch(f"/api/diaries/{diary_id}/reply", json={"at": one["at"], "text": "자막 바꾸기"})
    assert edit.status_code == 404  # 목소리 답장은 고치지 않는다 — 지우고 다시
    assert client.delete(f"/api/diaries/{diary_id}/reply", params={"at": one["at"]}).status_code == 204
    assert storage.get(_key(one)) is None and storage.get(_key(two))  # 지운 칸의 소리만
    assert client.delete(f"/api/diaries/{diary_id}/reply").status_code == 204  # at 없이 = 내 것 모두
    assert _stored(diary_id) == [] and storage.get(_key(two)) is None


def test_only_on_elder_diary_and_only_members(client, monkeypatch):
    room_id = setup_elder(client)["room_id"]
    assert _voice(client, _diary(room_id, "FAMILY")).json()["code"] == "VOICE_REPLY_NOT_ALLOWED"
    diary_id = _diary(room_id)
    url = _voice(client, diary_id).json()["reactions"][0]["audio_url"]
    monkeypatch.setattr(stt, "to_mp3", lambda audio, sec, kbps: b"ID3")  # 못 푸는 녹음 — 머리글만
    assert _voice(client, diary_id).json()["code"] == "AUDIO_INVALID"
    assert client.get(url).status_code == 200  # 실패한 요청은 앞의 답장을 건드리지 않는다
    signup(client)  # 다른 가족방 사람 — 있는지도 모르게 404
    assert _voice(client, diary_id).status_code == 404
    assert client.get(url).status_code == 404


def test_withdraw_removes_my_voice_but_keeps_others(client):
    room_id = setup_elder(client)["room_id"]
    diary_id = _diary(room_id)
    assert client.post(f"/api/diaries/{diary_id}/reply", json={"text": "잘 지내세요"}).status_code == 200  # 방장 글
    _join(client, room_id)  # 손주로 로그인
    key = _key(next(c for c in _voice(client, diary_id).json()["reactions"] if c.get("audio_url")))
    out = client.post("/api/auth/withdraw", json={"password": "test1234", "transfers": []})
    assert out.status_code == 200, out.text
    assert [c.get("text") for c in _stored(diary_id)] == ["잘 지내세요"] and storage.get(key) is None
