"""그림일기 이미지 어댑터 (D4, D36). 시그니처 고정: generate(draw_spec: dict, seed: int) -> bytes | None

draw_spec = {"objects": ["화투패", "찻잔"]} — 어르신이 말씀하신 사물 1~3개 (prompts/diary_draft.md 가 고른다.
사람·얼굴·건물·특정 장소·글자 없음). 사진 없는 일기만 그린다.
게시가 그림을 기다리므로(D36) 실제 호출은 20초 안에 끝나야 한다. 시간 초과·실패는 예외나 None → 글만 게시.
결과는 JPEG 바이트 (저장 key 가 .jpg 이고 /api/media 가 image/jpeg 로 내보낸다. PNG 로 오면 JPEG 로 바꿔 돌려준다).

IMAGE_PROVIDER=mock: 개발(APP_ENV=dev)은 도형 자리표시 그림(글자 없음) — 키 없이 그림일기 화면 흐름을 보려고.
배포(APP_ENV=deploy)는 None → 글만 게시 (가짜 그림이 진짜 그림일기로 가족에게 가지 않게).
실제 제공자(cloudflare Workers AI FLUX.2 klein, 손그림체·시드 고정)는 CF_* 키를 받은 뒤 담당자(11/9 배정)가 채운다.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

from PIL import Image, ImageDraw

from app.config import settings

log = logging.getLogger("app.ai")


def _placeholder(draw_spec: dict[str, Any], seed: int) -> bytes:
    """mock: 그릴 사물 수만큼 동그라미를 그린 512px JPEG. 진짜 그림이 아니라는 게 한눈에 보인다."""
    n = max(1, min(3, len(draw_spec.get("objects") or [])))
    img = Image.new("RGB", (512, 512), (255, 248, 231))
    pen = ImageDraw.Draw(img)
    colors = [(244, 162, 97), (42, 157, 143), (233, 196, 106)]
    for i in range(n):
        cx, r = 512 * (i + 1) // (n + 1), 60 + (seed + 17 * i) % 30
        pen.ellipse((cx - r, 256 - r, cx + r, 256 + r), fill=colors[i], outline=(60, 60, 60), width=6)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def generate(draw_spec: dict[str, Any], seed: int = 0) -> bytes | None:
    provider = settings.IMAGE_PROVIDER
    t0 = time.perf_counter()
    try:
        if provider == "mock":
            return _placeholder(draw_spec, seed) if settings.is_dev else None
        if provider == "cloudflare":
            raise NotImplementedError(
                "Workers AI 연동은 CF_ACCOUNT_ID/CF_API_TOKEN 을 받은 뒤 구현 (backend/app/ai/image.py)"
            )
        raise NotImplementedError(f"IMAGE_PROVIDER={provider} 는 아직 없습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("image provider=%s ms=%d seed=%d", provider, ms, seed)
