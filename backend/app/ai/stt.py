"""STT 어댑터 (D4). 시그니처 고정: transcribe(audio: bytes, hints: list[str]) -> (text, confidence)

STT_PROVIDER=mock 이면 고정 문장을 돌려준다. 실제 제공자(rtzr 등)는 키를 받은 뒤 담당자가 채운다.
오디오는 전사 직후 폐기 — 어디에도 저장하지 않는다 (NFR-AN-001).
"""

from __future__ import annotations

import logging
import time

from app.config import settings

log = logging.getLogger("app.ai")


def transcribe(audio: bytes, hints: list[str] | None = None) -> tuple[str, float]:
    provider = settings.STT_PROVIDER
    t0 = time.perf_counter()
    try:
        if provider == "mock":
            return "옛날에 가족들이랑 같이 찍은 사진이에요", 0.95
        if provider == "rtzr":
            raise NotImplementedError("RTZR 연동은 RTZR_CLIENT_ID/SECRET 을 받은 뒤 구현 (backend/app/ai/stt.py)")
        raise NotImplementedError(f"STT_PROVIDER={provider} 는 아직 없습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("stt provider=%s ms=%d bytes=%d", provider, ms, len(audio))
