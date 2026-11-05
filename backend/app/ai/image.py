"""그림일기 이미지 어댑터 (D4). 시그니처 고정: generate(draw_spec: dict, seed: int) -> bytes | None

None 이면 그림 없이 글만 게시한다. IMAGE_PROVIDER=mock 은 항상 None.
실제 제공자(cloudflare Workers AI FLUX.2 klein)는 CF_* 키를 받은 뒤 담당자가 채운다. 결과는 JPEG/PNG 바이트.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings

log = logging.getLogger("app.ai")


def generate(draw_spec: dict[str, Any], seed: int = 0) -> bytes | None:
    provider = settings.IMAGE_PROVIDER
    t0 = time.perf_counter()
    try:
        if provider == "mock":
            return None
        if provider == "cloudflare":
            raise NotImplementedError(
                "Workers AI 연동은 CF_ACCOUNT_ID/CF_API_TOKEN 을 받은 뒤 구현 (backend/app/ai/image.py)"
            )
        raise NotImplementedError(f"IMAGE_PROVIDER={provider} 는 아직 없습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("image provider=%s ms=%d seed=%d", provider, ms, seed)
