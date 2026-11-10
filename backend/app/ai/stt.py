"""STT 어댑터 (D4). 시그니처 고정: transcribe(audio: bytes, hints: list[str]) -> (text, confidence)

STT_PROVIDER=mock 이면 고정 문장을 돌려준다. rtzr 는 리턴제로 스트리밍 STT (D35·D46):
  녹음(webm/opus 등) → ffmpeg 로 16kHz mono PCM → WebSocket 에 한꺼번에 보내고 "EOS" → 확정 문장(final)을 이어 붙인다.
오디오는 전사 직후 폐기 — 어디에도 저장하지 않는다 (NFR-AN-001). ffmpeg 와도 파이프로만 주고받는다(임시 파일 없음).
전사 글·토큰은 로그에 남기지 않는다 (D15). 로그는 제공자·걸린 시간·크기·소리 길이(리턴제로 과금 단위)만.
실측(11/10, 맥·서울, 변환 포함): 말 1~11초 → 0.4~0.7초(최대 0.9), 19초 → 0.9초, 58초 → 2.0초.
토큰 발급 0.6~1.0초는 6시간에 한 번.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from collections.abc import Callable
from urllib.parse import urlencode

import httpx
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.frames import OK_CLOSE_CODES
from websockets.protocol import State
from websockets.sync.client import connect

from app.config import STT_MAX_SEC, settings

log = logging.getLogger("app.ai")

RTZR_AUTH_URL = "https://openapi.vito.ai/v1/authenticate"
RTZR_WS_URL = "wss://openapi.vito.ai/v1/transcribe:streaming"
RATE = 16000  # ffmpeg 가 맞춰 주는 샘플레이트. 16-bit mono 라 1초에 RATE * 2 바이트
CHUNK = RATE * 2  # 1초 분량씩 보낸다
# 변환 + 토큰 + 연결 + 전사를 합친 상한. 실측 최장(58초 말)이 2.0초. 화면은 /api/stt 를 따로 끊지 않으므로 여기서 끊는다
RTZR_TIMEOUT_SEC = 8.0
TOKEN_MARGIN_SEC = 1800  # 토큰 수명은 6시간. 만료 30분 전부터 새로 받는다
KEYWORD = re.compile(r"[가-힣 ]{1,20}")  # 리턴제로 키워드 규칙: 한글·공백만, 20자 이하 (100개까지)

_token_lock = threading.Lock()  # 동기 엔드포인트는 스레드풀에서 겹쳐 돈다 (D3)
_token: tuple[str, float] | None = None  # (토큰, 만료 시각 epoch 초). 프로세스 메모리 (워커 1개, D9)


class BadAudio(Exception):
    """소리로 읽을 수 없는 파일 (ffmpeg 가 풀지 못함)."""


def transcribe(audio: bytes, hints: list[str] | None = None) -> tuple[str, float]:
    provider = settings.STT_PROVIDER
    t0 = time.perf_counter()
    stats = {"sec": 0.0}  # 리턴제로에 보낸 소리 길이(과금 단위). 중간에 실패해도 로그에 남게 _rtzr 가 채운다
    try:
        if provider == "mock":
            return "옛날에 가족들이랑 같이 찍은 사진이에요", 0.95
        if provider == "rtzr":
            return _rtzr(audio, hints or [], stats)
        raise NotImplementedError(f"STT_PROVIDER={provider} 는 아직 없습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("stt provider=%s ms=%d bytes=%d sec=%.1f", provider, ms, len(audio), stats["sec"])


def _pcm(audio: bytes, timeout: float) -> bytes:
    """녹음을 16kHz mono 16-bit PCM(헤더 없음)으로. STT_MAX_SEC 뒤는 버린다(과금·메모리 상한).

    올라온 파일은 믿을 수 없는 입력이라 ffmpeg 가 할 수 있는 일을 좁힌다.
    -protocol_whitelist pipe: 재생목록(m3u8 등)이어도 서버 파일·다른 주소를 열지 못한다.
    -format_whitelist·-codec_whitelist: 브라우저 녹음 형식(webm·ogg/opus, mp4/aac)만 연다. 그림·영상을 풀게 두면
      1MB 안 되는 파일 하나가 메모리 700MB 를 쓴다(실측. 좁히면 12MB 에서 거절).
    -v quiet: 깨진 파일은 오류 글을 100MB 넘게 쏟는다. 쓰지 않는 글이라 끈다.
    """
    cmd = ["ffmpeg", "-v", "quiet", "-protocol_whitelist", "pipe"]
    cmd += ["-format_whitelist", "matroska,webm,mov,mp4,ogg", "-codec_whitelist", "opus,libopus,vorbis,aac"]
    cmd += ["-i", "pipe:0", "-t", str(STT_MAX_SEC), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"]
    p = subprocess.run(cmd, input=audio, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise BadAudio
    return p.stdout


def _get_token(left: Callable[[], float]) -> str:
    """left() 는 남은 시간(초). 앞 요청이 토큰을 받는 동안 기다린 시간도 상한에서 뺀다."""
    global _token
    if not _token_lock.acquire(timeout=left()):
        raise TimeoutError
    try:
        if _token and _token[1] - time.time() > TOKEN_MARGIN_SEC:
            return _token[0]
        r = httpx.post(
            RTZR_AUTH_URL,
            data={"client_id": settings.RTZR_CLIENT_ID, "client_secret": settings.RTZR_CLIENT_SECRET},
            timeout=left(),
        )
        if r.is_error:
            log.warning("stt rtzr auth status=%d", r.status_code)
            r.raise_for_status()
        body = r.json()
        _token = (body["access_token"], float(body["expire_at"]))
        return _token[0]
    finally:
        _token_lock.release()


def _rtzr(audio: bytes, hints: list[str], stats: dict[str, float]) -> tuple[str, float]:
    """리턴제로 스트리밍 STT. 반환: (전사, 신뢰도). 재시도 없음 — 실패하면 화면이 다시 말하게 한다."""
    global _token
    if not (settings.RTZR_CLIENT_ID and settings.RTZR_CLIENT_SECRET):
        raise RuntimeError("STT_PROVIDER=rtzr 인데 RTZR_CLIENT_ID/RTZR_CLIENT_SECRET 이 비어 있음 (.env)")
    deadline = time.monotonic() + RTZR_TIMEOUT_SEC

    def left() -> float:
        return max(0.1, deadline - time.monotonic())

    pcm = _pcm(audio, left())
    stats["sec"] = len(pcm) / CHUNK
    if not pcm:
        return "", 0.0  # 소리가 없으면 연결하지 않는다 (연결마다 최소 10초가 과금된다)
    query = {
        "sample_rate": RATE,
        "encoding": "LINEAR16",
        "use_itn": "true",
        "use_punctuation": "true",
        "use_disfluency_filter": "false",
        "use_profanity_filter": "false",
    }
    # 이름·호칭 힌트 → 키워드 부스팅. 리턴제로는 설정을 주소(쿼리)로만 받는다. 이 주소는 로그에 남기지 않는다
    keywords = [h for h in hints if KEYWORD.fullmatch(h)][:100]
    if keywords:
        query["keywords"] = ",".join(keywords)
    finals: list[tuple[str, float]] = []
    try:
        with connect(
            f"{RTZR_WS_URL}?{urlencode(query)}",
            additional_headers={"Authorization": f"Bearer {_get_token(left)}"},
            open_timeout=left(),
            close_timeout=0.1,  # 리턴제로는 닫기 신호를 보낸 뒤 2초쯤 있다가 연결을 끊는다. 그걸 기다리지 않는다
        ) as ws:
            for i in range(0, len(pcm), CHUNK):  # 실시간보다 빨리 보내도 받는다 (문서에는 없음, 11/10 실측)
                ws.socket.settimeout(left())  # 보내기에도 상한: 상대가 읽지 않으면 send 가 끝없이 기다린다
                ws.send(pcm[i : i + CHUNK])
            ws.socket.settimeout(left())
            ws.send("EOS")
            closing = False
            while True:
                try:
                    raw = ws.recv(timeout=0.02)
                except TimeoutError:
                    if closing:
                        break  # 닫기 신호 뒤 남은 글까지 다 읽었다
                    if ws.state is not State.OPEN:
                        closing = True  # 닫기 신호 도착 = 마지막 final 까지 보냈다는 뜻. 한 번 더 읽고 끝낸다
                    elif time.monotonic() > deadline:
                        raise
                    continue
                except ConnectionClosed:
                    break
                msg = json.loads(raw)
                if msg.get("final"):
                    alt = msg["alternatives"][0]
                    finals.append((alt["text"].strip(), float(alt.get("confidence") or 0.0)))
        # with 를 나오면 연결이 다 닫혀 close_code 가 정해진다. 정상(1000·1001·코드 없음)이 아니면 글이 잘렸을 수 있다
        if ws.close_code not in OK_CLOSE_CODES:
            log.warning("stt rtzr closed code=%s", ws.close_code)
            raise RuntimeError("리턴제로가 전사 도중 연결을 비정상 종료")
    except InvalidStatus as e:  # 연결 거부: 401 토큰, 429 사용량·동시 5채널 초과 등
        log.warning("stt rtzr connect status=%d", e.response.status_code)
        if e.response.status_code == 401:
            with _token_lock:
                _token = None  # 다음 요청이 새 토큰을 받는다
        raise
    spoken = [(text, conf) for text, conf in finals if text]
    # 말 사이가 0.5초 넘게 뜨면 문장이 나뉘어 온다. 신뢰도는 가장 낮은 문장을 따른다(하나라도 애매하면 확인받는다)
    confidence = min((conf for _, conf in spoken), default=0.0)
    return " ".join(text for text, _ in spoken), min(1.0, max(0.0, confidence))
