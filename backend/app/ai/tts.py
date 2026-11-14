"""TTS 어댑터 (D4). 시그니처 고정: synthesize(text, speed, voice) -> bytes | None (voice 는 D74 에서 더함)

None 이면 브라우저 speechSynthesis 로 읽는다 (D5). TTS_PROVIDER=mock 은 항상 None.
google 은 Cloud Text-to-Speech Chirp 3 HD ko-KR (D35·D46). 결과는 mp3 바이트.
말 속도는 여기서 바꾸지 않는다: 1.0배로 합성하고 화면이 audio.playbackRate 로 늦춘다 (D46). speed 는 시그니처·로그용.
읽을 글은 로그에 남기지 않는다 (D15). 키는 주소가 아니라 헤더로 보낸다(httpx 가 요청 주소를 로그에 남긴다).
실측(11/10, 맥·서울): 9자 0.8초, 26자 0.9초, 58자 1.6초, 102자 2.4초, 200자 5.3초, 400자 9.2초
(약 0.6초 + 글자당 0.02초).
"""

from __future__ import annotations

import base64
import logging
import time
from functools import lru_cache

import httpx

from app.config import TTS_PER_DAY, settings
from app.security import daily_allowed

log = logging.getLogger("app.ai")

# 전역 주소. 도쿄 리전 주소(asia-northeast1-)는 더 느렸다 (실측 1.15초 대 0.96초)
GOOGLE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
# 목소리 2개 중 어르신이 고른다 (D74, TEST-01 청취 평가 — FR-VS-004 '목소리 1개 고정'을 바꿈). 가족방 칸 tts_voice
VOICES = {"FEMALE": "ko-KR-Chirp3-HD-Kore", "MALE": "ko-KR-Chirp3-HD-Charon"}
# 합성 시간이 글 길이에 비례해서 상한도 길이에 맞춘다: 대화 한 턴(120자 이하)은 6.6초, 일기 낭독(400자)은 15초.
# LLM 이 평소(1.5~3초)면 TTS 가 막혀도 화면의 15초 포기(VoiceSession) 전에 자막만으로 넘어간다.
# LLM 이 8.4초를 넘긴 턴(재시도 포함 최대 12초)에서 TTS 까지 막히면 15초를 넘는다
TTS_BASE_SEC = 3.0
TTS_PER_CHAR_SEC = 0.03


def synthesize(text: str, speed: float = 0.90, voice: str = "FEMALE") -> bytes | None:
    """voice = FEMALE | MALE (가족방 tts_voice, D74). 모르는 값은 FEMALE."""
    provider = settings.TTS_PROVIDER
    t0 = time.perf_counter()
    try:
        if provider == "mock":
            return None
        if provider == "google":
            if not daily_allowed("tts", TTS_PER_DAY):  # 실패가 아니라 상한 → 가족 알림 없이 브라우저 목소리 (D5·D46)
                log.warning("tts daily cap")
                return None
            return _google(text, voice if voice in VOICES else "FEMALE")
        raise NotImplementedError(f"TTS_PROVIDER={provider} 는 아직 없습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("tts provider=%s ms=%d chars=%d speed=%.2f voice=%s", provider, ms, len(text), speed, voice)


# 같은 문장(무응답 때 다시 묻기·고정 안내)은 다시 합성하지 않는다 (FR-VS-004) — 목소리마다 따로. 실패는 캐시되지 않는다
@lru_cache(maxsize=128)
def _google(text: str, voice: str = "FEMALE") -> bytes:
    """Google Chirp 3 HD. 재시도 없음 — 실패하면 부른 쪽이 자막만으로 넘어간다 (D5)."""
    if not settings.GOOGLE_TTS_API_KEY:
        raise RuntimeError("TTS_PROVIDER=google 인데 GOOGLE_TTS_API_KEY 가 비어 있음 (.env)")
    r = httpx.post(
        GOOGLE_URL,
        headers={"X-Goog-Api-Key": settings.GOOGLE_TTS_API_KEY},
        json={
            "input": {"text": text},
            "voice": {"languageCode": "ko-KR", "name": VOICES[voice]},
            "audioConfig": {"audioEncoding": "MP3"},
        },
        timeout=TTS_BASE_SEC + TTS_PER_CHAR_SEC * len(text),
    )
    if r.is_error:
        log.warning("tts google status=%d", r.status_code)
        r.raise_for_status()
    return base64.b64decode(r.json()["audioContent"])
