"""11/25 실사용 피드백 (2차): 어르신 목소리 답장 저장 · 기분 체크 9번 109 안내 · 어르신 화면 이름 '별명 (이름)'.

ffmpeg 는 부르지 않는다(stt.to_mp3 를 바꿔 끼움). 가족 한마디 여러 개는 test_diary_reply.py·test_voice_reply.py.
"""

import pytest
from sqlalchemy import delete, update

from app.ai import stt
from app.config import VOICE_REPLY_KBPS
from app.db import SessionLocal
from app.models import Notification, RoomMember
from app.services import storage
from tests.conftest import setup_elder
from tests.test_reactions import _diary, _join, _react, _stored

AUDIO = {"audio": ("voice.webm", b"fake-webm", "audio/webm")}


@pytest.fixture(autouse=True)
def fake_mp3(monkeypatch):
    """5초짜리 mp3 인 척 — 고정 비트레이트라 길이는 바이트로 정해진다."""
    monkeypatch.setattr(stt, "to_mp3", lambda audio, sec, kbps: b"\xff" * (VOICE_REPLY_KBPS * 125 * 5))


@pytest.fixture(autouse=True)
def drop_reply_notices():
    """이 파일이 만든 ELDER_REPLY 알림을 지운다 — 시험 DB 는 테스트끼리 같이 쓰고,
    다른 파일(옛 마이그레이션 다시 돌리기·'첫 ELDER_REPLY 알림' 확인)이 그 알림이 없다고 본다."""
    yield
    with SessionLocal() as db:
        db.execute(delete(Notification).where(Notification.kind == "ELDER_REPLY"))
        db.commit()


def _elder_voice(client, diary_id, text):
    return client.post(f"/api/elder/diaries/{diary_id}/voice-reply", files=AUDIO, data={"text": text})


def _elder_cell(diary_id):
    return next(r for r in _stored(diary_id) if r["by"] == "ELDER" and r["kind"] == "REPLY")


# ---------------------------------------------------------------- 어르신 목소리 답장
def test_elder_voice_reply_is_kept_for_family(client, monkeypatch):
    family = _diary(setup_elder(client)["room_id"], "FAMILY")
    r = _elder_voice(client, family, "  좋구나\n고맙다 ")
    assert r.status_code == 200, r.text
    (cell,) = [x for x in r.json()["reactions"] if x["by"] == "ELDER"]
    assert (cell["text"], cell["audio_sec"]) == ("좋구나 고맙다", 5)  # 글은 …/reply 와 같은 검사(한 줄)
    seen = client.get(f"/api/diaries/{family}").json()["reactions"]  # 가족 화면에도 소리 주소
    assert [x["audio_url"] for x in seen if x["by"] == "ELDER"] == [cell["audio_url"]]
    first = _elder_cell(family)["audio_key"]
    assert storage.get(first)

    put = []
    monkeypatch.setattr(storage, "put", lambda key, *a, **k: put.append(key))
    _elder_voice(client, family, "좋구나 고맙다")  # 두 번 누름 — 칸은 그대로, 새로 올린 소리는 버린다
    assert _elder_cell(family)["audio_key"] == first and storage.get(first) and storage.get(put[0]) is None
    monkeypatch.undo()

    client.post(f"/api/elder/diaries/{family}/reply", json={"text": "또 보자"})  # 글만 새로 → 옛 소리 지움
    assert "audio_key" not in _elder_cell(family) and storage.get(first) is None


def test_deleting_family_diary_drops_elder_voice(client):
    family = _diary(setup_elder(client)["room_id"], "FAMILY")  # 쓴 사람 = 이 클라이언트의 가족
    _elder_voice(client, family, "좋구나")
    key = _elder_cell(family)["audio_key"]
    assert client.delete(f"/api/diaries/{family}").status_code == 204
    assert storage.get(key) is None


def test_elder_voice_reply_checks(client, monkeypatch):
    room_id = setup_elder(client)["room_id"]
    family, elder = _diary(room_id, "FAMILY"), _diary(room_id)
    assert _elder_voice(client, family, "가" * 41).status_code == 422
    assert _elder_voice(client, elder, "고맙다").status_code == 409  # 어르신 일기에는 답 없음
    monkeypatch.setattr(stt, "to_mp3", lambda audio, sec, kbps: b"")  # 못 푸는 소리 → 글만 보낸다
    assert _elder_voice(client, family, "고맙다").status_code == 200
    assert "audio_key" not in _elder_cell(family)


# ---------------------------------------------------------------- 기분 체크 9번 → 109
def test_item9_gives_109(client):
    setup_elder(client)
    saved = client.post("/api/elder/mood-check", json={"kind": "PHQ9", "answers": [0] * 8 + [1]}).json()
    assert saved["help_call"] is True and "109" in saved["say"] and "가족" not in saved["say"]
    plain = client.post("/api/elder/mood-check", json={"kind": "PHQ9", "answers": [0] * 9}).json()
    assert plain["help_call"] is False


# ---------------------------------------------------------------- 어르신 화면 이름 '별명 (이름)'
def test_elder_sees_nickname_with_name(client):
    room_id = setup_elder(client)["room_id"]
    diary = _diary(room_id)
    _join(client, room_id)
    me = client.get("/api/auth/me")
    me, user_id = me.json()["name"], me.json()["user_id"]
    with SessionLocal() as db:
        db.execute(update(RoomMember).where(RoomMember.user_id == user_id).values(nickname="손주"))
        db.commit()
    _react(client, diary, "HEART")
    (heart,) = client.get("/api/elder/family-news").json()["hearts"]
    assert heart["name"] == f"손주 ({me})"
    (cell,) = client.get("/api/elder/diaries").json()["diaries"][0]["reactions"]  # 어르신 '지난 일기'
    assert cell["name"] == f"손주 ({me})"
    assert client.get(f"/api/diaries/{diary}").json()["reactions"][0]["name"] == f"{me}(손주)"  # 가족 화면 그대로
