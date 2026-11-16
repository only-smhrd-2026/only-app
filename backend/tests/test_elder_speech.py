"""어르신 화면 읽어 주기 (D78) — 기기만, 가족방이 고른 목소리, 소리를 못 만들면 null, 글자 수·분당 상한.

유료 API 는 부르지 않는다: 테스트는 TTS 가 mock 이고, 소리가 필요한 곳은 tts.synthesize 를 바꿔 흉내 낸다.
"""

import base64

from app import security
from app.ai import tts
from app.db import SessionLocal
from app.models import FamilyRoom
from tests.conftest import setup_elder

MP3 = base64.b64encode(b"mp3").decode()


def _speech(client, text="순자 할머니, 같이 이야기해 볼까요?"):
    return client.post("/api/elder/speech", json={"text": text})


def test_speech_needs_elder_device(client):
    assert _speech(client).status_code == 401


def test_speech_uses_room_voice(client, monkeypatch):
    ctx = setup_elder(client)
    with SessionLocal() as db:
        db.get(FamilyRoom, ctx["room_id"]).tts_voice = "MALE"
        db.commit()
    seen = []
    monkeypatch.setattr(tts, "synthesize", lambda text, speed, voice: seen.append((text, voice)) or b"mp3")
    r = _speech(client)
    assert r.status_code == 200 and r.json() == {"audio_b64": MP3}
    assert seen == [("순자 할머니, 같이 이야기해 볼까요?", "MALE")]


def test_speech_without_sound_is_null(client, monkeypatch):
    setup_elder(client)
    assert _speech(client).json() == {"audio_b64": None}  # mock — 화면이 기기 목소리로

    def boom(*args):
        raise RuntimeError("제공자 장애")

    monkeypatch.setattr(tts, "synthesize", boom)
    r = _speech(client)
    assert r.status_code == 200 and r.json() == {"audio_b64": None}


def test_speech_limits(client, monkeypatch):
    setup_elder(client)
    assert _speech(client, "").status_code == 422
    assert _speech(client, "가" * 201).status_code == 422
    monkeypatch.setattr(security, "SPEECH_RATE_PER_MIN", 2)
    monkeypatch.setattr(tts, "synthesize", lambda *args: b"mp3")
    assert [_speech(client).json()["audio_b64"] for _ in range(3)] == [MP3, MP3, None]  # 셋째는 분당 상한
