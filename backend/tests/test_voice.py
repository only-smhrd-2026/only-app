"""진짜 음성 (AI-02 #14, D46) — /api/stt 응답 규칙, 리턴제로·Google 어댑터, 턴 응답에 실리는 음성.

유료 API 와 ffmpeg 는 부르지 않는다(httpx.post · connect · subprocess.run 을 바꿔 끼움). ffmpeg 가 없는 PC 에서도 돈다.
"""

import base64
import json
import logging
import subprocess
import threading
import time
import types
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import func, select
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response
from websockets.protocol import State

from app import security
from app.ai import llm, stt, tts
from app.ai.schemas import CoachTurn
from app.config import LLM_PER_DAY, STT_MAX_CHARS, STT_PER_DAY, TTS_PER_DAY, settings, today_kst
from app.db import SessionLocal, engine
from app.models import Notification
from tests.conftest import setup_elder, signup

AUDIO = {"audio": ("speech.webm", b"\x1a\x45\xdf\xa3 fake", "audio/webm")}


@pytest.fixture(autouse=True)
def _fresh_stt_rate_counter():
    """호출 횟수 카운터는 프로세스 메모리라 테스트마다 비운다 (TestClient 는 전부 같은 IP)."""
    security._stt_hits.clear()
    security._daily_hits.clear()


def test_stt_endpoint_rules(client, monkeypatch):
    """mock 전사는 200. 무음·못 읽는 녹음은 422, 제공자 장애는 503(예외 글은 응답에 없음), 긴 전사는 500자까지."""
    assert client.post("/api/stt", files=AUDIO).status_code == 401  # 로그인·기기 연결 없이는 못 부른다
    signup(client)
    r = client.post("/api/stt", files=AUDIO)
    assert r.status_code == 200, r.text
    assert r.json() == {"transcript": "옛날에 가족들이랑 같이 찍은 사진이에요", "confidence": 0.95}
    held = []  # STT 하는 동안 쥐고 있는 DB 연결 수

    def answer(result):
        def fake(audio, hints):
            held.append(engine.pool.checkedout())
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(stt, "transcribe", fake)
        return client.post("/api/stt", files=AUDIO)

    r = answer(("", 0.0))  # 무음. 빈 글을 200 으로 주면 화면의 [맞아요] 뒤 턴이 422 로 대화를 끝낸다
    assert r.status_code == 422 and r.json()["code"] == "STT_EMPTY"
    r = answer(stt.BadAudio())
    assert r.status_code == 422 and r.json()["code"] == "AUDIO_INVALID"
    r = answer(RuntimeError("wss://secret-address"))
    assert r.status_code == 503 and r.json()["code"] == "STT_UNAVAILABLE" and "secret" not in r.text
    r = answer(("가" * (STT_MAX_CHARS + 100), 0.9))
    assert r.status_code == 200 and len(r.json()["transcript"]) == STT_MAX_CHARS
    assert held == [0] * 4  # 인증 확인에 쓴 DB 연결은 STT(최대 8초) 전에 돌려준다 — 몰려도 다른 API 가 안 멈추게


def test_stt_rate_limit(client, monkeypatch):
    """같은 IP 에서 분당 상한을 넘으면 429 (돈이 드는 STT 를 무제한으로 못 부르게). 로그인 안 한 요청은 세지 않는다."""
    monkeypatch.setattr(security, "STT_RATE_PER_MIN", 2)
    assert client.post("/api/stt", files=AUDIO).status_code == 401
    signup(client)
    codes = [client.post("/api/stt", files=AUDIO).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_stt_daily_cap(client, monkeypatch):
    """서버 전체 하루 상한을 넘으면 429 STT_DAILY_LIMIT, 리턴제로는 부르지 않는다 (D46)."""
    signup(client)
    monkeypatch.setattr(settings, "STT_PROVIDER", "rtzr")
    monkeypatch.setattr(stt, "transcribe", lambda *a, **k: pytest.fail("상한을 넘었는데 STT 를 불렀다"))
    monkeypatch.setitem(security._daily_hits, ("stt", today_kst()), STT_PER_DAY)
    r = client.post("/api/stt", files=AUDIO)
    assert r.status_code == 429 and r.json()["code"] == "STT_DAILY_LIMIT"


def test_tts_llm_daily_cap(monkeypatch):
    """하루 상한을 넘으면 Google TTS 는 None(브라우저 목소리), Claude 는 LlmError(고정 문장).

    유료 API 는 부르지 않는다 (D46)."""
    monkeypatch.setattr(settings, "TTS_PROVIDER", "google")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    calls = []
    monkeypatch.setattr(tts, "_google", lambda text: calls.append(text) or b"mp3")
    monkeypatch.setitem(security._daily_hits, ("tts", today_kst()), TTS_PER_DAY - 1)
    assert tts.synthesize("가") == b"mp3"  # 상한 전 마지막 1번은 부르고 센다
    assert tts.synthesize("나") is None and calls == ["가"]
    monkeypatch.setattr(llm, "_anthropic", lambda *a: pytest.fail("상한을 넘었는데 Claude 를 불렀다"))
    monkeypatch.setitem(security._daily_hits, ("llm", today_kst()), LLM_PER_DAY)
    with pytest.raises(llm.LlmError):
        llm.call_json("memory_coach", {}, CoachTurn)


class FakeWs:
    """리턴제로 흉내. EOS 뒤에 script 를 차례로 내준다: dict 는 받은 글, "CLOSE" 는 닫기 신호(연결은 아직 안 끊김)."""

    close_code = 1000  # 정상 종료. 어댑터가 with 를 나온 뒤 본다

    def __init__(self, script):
        self.script, self.sent, self.state = list(script), [], State.OPEN
        self.timeouts = []
        self.socket = types.SimpleNamespace(settimeout=self.timeouts.append)  # 보내기 시간 제한을 받는 소켓 흉내

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send(self, data):
        self.sent.append(data)

    def recv(self, timeout=None):
        if "EOS" in self.sent and self.script:
            item = self.script.pop(0)
            if item != "CLOSE":
                return json.dumps(item)
            self.state = State.CLOSING
        time.sleep(timeout or 0)  # 진짜처럼 기다린 뒤 알린다 (상한 검사가 깨지면 끝나지 않는 대신 실패하게)
        raise TimeoutError


def _rtzr(monkeypatch, script, pcm: bytes | None = b"\0" * 80_000) -> dict:
    """STT_PROVIDER=rtzr 로 켜고 바깥으로 나가는 길 3개(ffmpeg·토큰·WebSocket)를 막는다. pcm=None 은 ffmpeg 실패."""
    calls = {"ffmpeg": [], "auth": 0, "ws": []}

    def fake_run(cmd, input, capture_output, timeout, **kw):
        calls["ffmpeg"].append(cmd)
        calls["ffmpeg_kw"] = kw  # 환경 변수·권한 (env·user)
        return subprocess.CompletedProcess(cmd, 1 if pcm is None else 0, stdout=pcm or b"", stderr=b"")

    def fake_post(url, data, timeout):
        calls["auth"] += 1
        body = {"access_token": "tok", "expire_at": time.time() + 6 * 3600}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    def fake_connect(url, additional_headers, open_timeout, close_timeout):
        ws = FakeWs(script)
        calls["ws"].append((url, additional_headers, ws))
        calls["close_timeout"] = close_timeout
        return ws

    monkeypatch.setattr(stt.subprocess, "run", fake_run)
    monkeypatch.setattr(stt.httpx, "post", fake_post)
    monkeypatch.setattr(stt, "connect", fake_connect)
    monkeypatch.setattr(stt, "_token", None)  # 토큰 캐시는 모듈 전역이라 테스트마다 비운다
    monkeypatch.setattr(settings, "STT_PROVIDER", "rtzr")
    monkeypatch.setattr(settings, "RTZR_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "RTZR_CLIENT_SECRET", "secret")
    return calls


def _final(text: str, confidence: float) -> dict:
    return {"final": True, "alternatives": [{"text": text, "confidence": confidence}]}


def test_rtzr_sends_whole_recording_and_joins_sentences(monkeypatch, caplog):
    """변환한 PCM 을 한꺼번에 보내고 EOS → 확정 문장을 이어 붙인다. 닫기 신호 뒤에 온 글도 읽고, 신뢰도는 최저값."""
    partial = {"final": False, "alternatives": [{"text": "옛날에", "confidence": 0}]}
    script = [partial, _final("옛날에 찍었어요.", 0.99), "CLOSE", _final(" 네, 맞아요. ", 0.62)]
    calls = _rtzr(monkeypatch, script)
    caplog.set_level(logging.INFO)
    monkeypatch.setenv("RTZR_CLIENT_SECRET", "secret")  # 배포처럼 키가 환경 변수에 있다 (docker-compose env_file)

    assert stt.transcribe(b"webm", ["순자 할머니", "bad1", "가" * 21]) == ("옛날에 찍었어요. 네, 맞아요.", 0.62)
    # 로그에는 숫자만 (D15): 전사 글·이름 힌트·토큰이 없다
    assert "sec=2.5" in caplog.text and not any(w in caplog.text for w in ("옛날에", "순자", "Bearer"))

    cmd = calls["ffmpeg"][0]  # 파이프로만 주고받고, 60초 뒤는 버리고, 다른 주소·파일은 못 열게
    assert cmd[0] == "ffmpeg" and "pipe:0" in cmd and cmd[-1] == "pipe:1"
    assert cmd[cmd.index("-t") + 1] == "60" and cmd[cmd.index("-protocol_whitelist") + 1] == "pipe"
    assert cmd[cmd.index("-fs") + 1] == str(60 * stt.CHUNK)  # -t 는 파일 속 시간표를 믿는다 → 출력 바이트로도 60초
    assert cmd[cmd.index("-v") + 1] == "quiet" and cmd[-7:-1] == ["-f", "s16le", "-ac", "1", "-ar", "16000"]
    # 그림·영상 디코더는 열지 않는다 (입력 옵션이라 -i 앞에 있어야 먹는다) (D46 ②, 아이폰 mp4/aac 포함)
    assert cmd.index("-format_whitelist") < cmd.index("-i") and cmd.index("-codec_whitelist") < cmd.index("-i")
    assert cmd[cmd.index("-format_whitelist") + 1] == "matroska,webm,mov,mp4,ogg"
    assert cmd[cmd.index("-codec_whitelist") + 1] == "opus,libopus,vorbis,aac"
    # 올라온 파일을 푸는 ffmpeg 에는 키가 든 환경 변수를 물려주지 않는다 (PATH 만)
    assert "RTZR_CLIENT_SECRET" not in calls["ffmpeg_kw"]["env"] and list(calls["ffmpeg_kw"]["env"]) == ["PATH"]
    url, headers, ws = calls["ws"][0]
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("wss://openapi.vito.ai/v1/transcribe:streaming?")
    assert query["sample_rate"] == ["16000"] and query["encoding"] == ["LINEAR16"]
    assert query["keywords"] == ["순자 할머니"]  # 한글·공백·20자 이하만 키워드로
    assert headers == {"Authorization": "Bearer tok"}
    assert ws.sent[-1] == "EOS" and b"".join(ws.sent[:-1]) == b"\0" * 80_000 and len(ws.sent) == 4  # 1초씩 3조각
    assert len(ws.timeouts) == 4 and all(0 < t <= stt.RTZR_TIMEOUT_SEC for t in ws.timeouts)  # 보낼 때마다 상한
    assert calls["close_timeout"] == 0.1  # 리턴제로가 2초 뒤에 끊는 것을 기다리지 않는다

    stt.transcribe(b"webm")
    assert calls["auth"] == 1 and "keywords" not in calls["ws"][1][0]  # 토큰은 6시간 동안 다시 받지 않는다
    monkeypatch.setattr(stt, "_token", ("old", time.time() + 60))  # 만료 30분 전부터는 새로 받는다
    stt.transcribe(b"webm")
    assert calls["auth"] == 2 and calls["ws"][2][1] == {"Authorization": "Bearer tok"}

    monkeypatch.setattr(stt.os, "geteuid", lambda: 0, raising=False)  # 배포 컨테이너는 root: ffmpeg 만 nobody 로
    stt.transcribe(b"webm")
    kw = calls["ffmpeg_kw"]
    assert kw["user"] == kw["group"] == 65534 and kw["extra_groups"] == [] and list(kw["env"]) == ["PATH"]


def test_rtzr_caps_sound_at_60s_and_stops_sending_at_deadline(monkeypatch):
    """시간표를 조작한 녹음은 ffmpeg 가 60초보다 길게 내놓을 수 있다 → 60초 분량만 보낸다(과금 상한).
    조각을 보내는 동안 상한이 지나면 남은 조각·EOS 를 보내지 않고 끊는다(TimeoutError → /api/stt 503)."""
    long_pcm = b"\0" * (61 * stt.CHUNK)
    calls = _rtzr(monkeypatch, [_final("네.", 0.9), "CLOSE"], pcm=long_pcm)
    assert stt.transcribe(b"webm") == ("네.", 0.9)
    assert sum(map(len, calls["ws"][0][2].sent[:-1])) == 60 * stt.CHUNK

    calls = _rtzr(monkeypatch, [_final("네.", 0.9), "CLOSE"], pcm=long_pcm)
    monkeypatch.setattr(stt, "RTZR_TIMEOUT_SEC", 0.05)

    def slow_send(self, data):  # 상대가 천천히 받는다: 조각마다 0.01초 (left() 최소 0.1초보다 짧게)
        time.sleep(0.01)
        self.sent.append(data)

    monkeypatch.setattr(FakeWs, "send", slow_send)
    with pytest.raises(TimeoutError):
        stt.transcribe(b"webm")
    assert "EOS" not in calls["ws"][0][2].sent


def test_rtzr_failures(monkeypatch):
    """소리가 없으면 연결(과금) 안 함, 못 읽으면 BadAudio, 닫기 신호가 안 오면 상한에서 끊음, 401 이면 토큰을 버림."""
    calls = _rtzr(monkeypatch, [], pcm=b"")
    assert stt.transcribe(b"webm") == ("", 0.0) and not calls["ws"]

    calls = _rtzr(monkeypatch, [], pcm=None)
    with pytest.raises(stt.BadAudio):
        stt.transcribe(b"not audio")
    assert not calls["ws"] and calls["auth"] == 0

    calls = _rtzr(monkeypatch, ["CLOSE"])  # 소리는 있는데 말이 없음(무음): 글 없이 닫기 신호만 온다
    assert stt.transcribe(b"webm") == ("", 0.0) and len(calls["ws"]) == 1

    _rtzr(monkeypatch, [_final("글은 왔지만", 0.9)])  # 닫기 신호가 끝내 안 옴
    monkeypatch.setattr(stt, "RTZR_TIMEOUT_SEC", 0.05)
    with pytest.raises(TimeoutError):
        stt.transcribe(b"webm")

    _rtzr(monkeypatch, [_final("첫 문장만.", 0.9), "CLOSE"])  # 오류 코드로 닫힘 → 잘린 글을 돌려주지 않는다
    monkeypatch.setattr(FakeWs, "close_code", 1011)
    with pytest.raises(RuntimeError):
        stt.transcribe(b"webm")

    calls = _rtzr(monkeypatch, [])
    monkeypatch.setattr(stt, "_token", ("old", time.time() + 6 * 3600))

    def refuse(*args, **kwargs):
        raise InvalidStatus(Response(401, "Unauthorized", Headers()))

    monkeypatch.setattr(stt, "connect", refuse)
    with pytest.raises(InvalidStatus):
        stt.transcribe(b"webm")
    assert stt._token is None and calls["auth"] == 0  # 다음 요청이 새 토큰을 받는다

    monkeypatch.setattr(settings, "RTZR_CLIENT_SECRET", "")
    with pytest.raises(RuntimeError):  # 키가 없으면 예외 → /api/stt 가 503
        stt.transcribe(b"webm")


def test_rtzr_token_wait_is_inside_deadline(monkeypatch):
    """앞 요청이 토큰을 받는 중(락을 쥠)이면 기다린 시간도 상한에 넣는다 — 겹친 요청이 8초씩 쌓이지 않게."""
    calls = _rtzr(monkeypatch, [])
    monkeypatch.setattr(stt, "RTZR_TIMEOUT_SEC", 0.05)
    errs = []  # 스레드 안의 pytest.raises 는 실패해도 경고로만 남아, 예외 종류는 여기 모아 본 스레드에서 비교한다

    def run():
        try:
            stt.transcribe(b"webm")
        except Exception as e:
            errs.append(type(e))

    t = threading.Thread(target=run)
    stt._token_lock.acquire()  # 다른 요청이 토큰을 받는 중인 상황
    t.start()
    t.join(2)
    stuck = t.is_alive()
    stt._token_lock.release()
    t.join()  # 가짜(monkeypatch)가 풀리기 전에 끝낸다
    assert not stuck and errs == [TimeoutError] and calls["auth"] == 0


def test_rtzr_401_waits_for_token_lock_only_until_deadline(monkeypatch):
    """401 로 토큰을 버릴 때도 락 대기는 상한 안 — 앞 요청이 토큰을 받는 중(락을 쥠)이어도 8초를 넘기지 않는다."""
    _rtzr(monkeypatch, [])
    monkeypatch.setattr(stt, "RTZR_TIMEOUT_SEC", 0.05)
    held = threading.Event()

    def hold():  # 느린 토큰 발급 흉내: 다른 요청이 락을 1초 쥔다
        with stt._token_lock:
            held.set()
            time.sleep(1)

    other = threading.Thread(target=hold)

    def refuse(*args, **kwargs):
        other.start()
        held.wait()
        raise InvalidStatus(Response(401, "Unauthorized", Headers()))

    monkeypatch.setattr(stt, "connect", refuse)
    t0 = time.monotonic()
    with pytest.raises(InvalidStatus):
        stt.transcribe(b"webm")
    took = time.monotonic() - t0
    other.join()
    assert took < 0.5


def test_google_tts_adapter(monkeypatch):
    """실제 제공자: 키는 헤더로, mp3 로 받고, 속도는 보내지 않는다(화면이 늦춘다). 같은 문장은 다시 합성하지 않는다."""
    sent = {"n": 0}
    reply = {"status": 200}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json, timeout=timeout, n=sent["n"] + 1)
        body = {"audioContent": base64.b64encode(b"mp3!").decode()}
        return httpx.Response(reply["status"], json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(tts.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "TTS_PROVIDER", "google")
    monkeypatch.setattr(settings, "GOOGLE_TTS_API_KEY", "key-123")
    tts._google.cache_clear()

    text = "그날 누구랑 가셨어요?"
    assert tts.synthesize(text, 0.85) == b"mp3!"
    assert sent["url"] == tts.GOOGLE_URL and sent["headers"] == {"X-Goog-Api-Key": "key-123"}  # 주소에는 키가 없다
    assert sent["body"] == {
        "input": {"text": text},
        "voice": {"languageCode": "ko-KR", "name": tts.VOICE},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    assert sent["timeout"] == pytest.approx(tts.TTS_BASE_SEC + tts.TTS_PER_CHAR_SEC * len(text))
    assert tts.synthesize(text, 0.70) == b"mp3!" and sent["n"] == 1  # 캐시

    reply["status"] = 429  # 한도 초과 → 예외 → 부른 쪽이 자막만
    with pytest.raises(httpx.HTTPStatusError):
        tts.synthesize("다른 문장이에요.")
    reply["status"] = 200
    assert tts.synthesize("다른 문장이에요.") == b"mp3!" and sent["n"] == 3  # 실패는 캐시되지 않는다

    monkeypatch.setattr(settings, "GOOGLE_TTS_API_KEY", "")
    with pytest.raises(RuntimeError):
        tts.synthesize("키가 없어요.")
    tts._google.cache_clear()


def test_turn_carries_tts_audio_and_survives_tts_failure(client, monkeypatch):
    """TTS 가 되면 턴 응답에 base64 음성이 실리고, 실패하면 자막만 + 가족 알림은 그 대화에 1건 (D5)."""
    ctx = setup_elder(client)

    def start():
        body = {"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]}
        r = client.post("/api/elder/sessions", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    monkeypatch.setattr(tts, "synthesize", lambda text, speed: b"mp3!")
    assert base64.b64decode(start()["ai"]["audio_b64"]) == b"mp3!"

    def broken(text, speed):
        raise httpx.ReadTimeout("slow")

    def alerts() -> int:
        with SessionLocal() as db:
            return db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.room_id == ctx["room_id"], Notification.kind == "TTS_ERROR")
            )

    monkeypatch.setattr(tts, "synthesize", broken)
    s = start()
    assert s["ai"]["audio_b64"] is None and s["ai"]["text"] and alerts() == 1
    for _ in range(3):  # 무응답 3단계째에 대화가 끝난다. 끝인사 합성이 또 실패해도 알림은 그 대화에 1건
        r = client.post(
            f"/api/elder/sessions/{s['session_id']}/turns", json={"input_type": "BUTTON", "event": "NO_RESPONSE"}
        )
    assert r.json()["state"] == "ENDED" and alerts() == 1
