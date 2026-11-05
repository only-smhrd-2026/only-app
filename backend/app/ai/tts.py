"""TTS 어댑터 (D4). 시그니처 고정: synthesize(text, speed) -> bytes | None

None 이면 브라우저 speechSynthesis 로 읽는다 (D5). TTS_PROVIDER=mock 은 항상 None.
실제 제공자(google 등)는 키를 받은 뒤 담당자가 채운다. 결과는 mp3 바이트.
"""

from __future__ import annotations

import logging
import time

from app.config import settings

log = logging.getLogger("app.ai")


def synthesize(text: str, speed: float = 0.85) -> bytes | None:
    provider = settings.TTS_PROVIDER
    t0 = time.perf_counter()
    try:
        if provider == "mock":
            return None
        if provider == "google":
            raise NotImplementedError("Google TTS 연동은 GOOGLE_TTS_API_KEY 를 받은 뒤 구현 (backend/app/ai/tts.py)")
        raise NotImplementedError(f"TTS_PROVIDER={provider} 는 아직 없습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("tts provider=%s ms=%d chars=%d speed=%.2f", provider, ms, len(text), speed)
