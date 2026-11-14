"""그림일기 이미지 어댑터 (D4, D36, D37). 시그니처 고정: generate(draw_spec: dict, seed: int) -> bytes | None

draw_spec = {"objects": ["teacup", "pumpkin"], "seed": 123} — 그릴 사물 1~3개, 영어 이름 (prompts/diary_draft.md 가
말씀하신 사물이나 하신 일에서 떠오르는 사물로 고른다. 사람·얼굴·건물·특정 장소·글자 없음). 고른 사물이 없으면
기분 그림 MOOD_OBJECTS[기분]. 시드는 일기마다 다르다(D69 — D37 의 '시드 0 고정'을 바꿈). 사진 없는 일기만 그린다.
게시가 그림을 기다리므로(D36) 실제 호출은 20초 안에 끝나야 한다. 시간 초과·실패는 예외나 None → 글만 게시.
결과는 JPEG 바이트 (저장 key 가 .jpg 이고 /api/media 가 image/jpeg 로 내보낸다. 받은 그림은 항상 JPEG 로 다시 인코딩).

IMAGE_PROVIDER=mock: 개발(APP_ENV=dev)은 도형 자리표시 그림(글자 없음) — 키 없이 그림일기 화면 흐름을 보려고.
배포(APP_ENV=deploy)는 None → 글만 게시 (가짜 그림이 진짜 그림일기로 가족에게 가지 않게).
IMAGE_PROVIDER=cloudflare: Workers AI FLUX.2 klein 4B (CF_ACCOUNT_ID·CF_API_TOKEN). 768px 1장 7~10초(11/6 실측).
"""

from __future__ import annotations

import base64
import io
import logging
import time
from typing import Any

import httpx
from PIL import Image, ImageDraw

from app.config import settings

log = logging.getLogger("app.ai")

CF_MODEL = "@cf/black-forest-labs/flux-2-klein-4b"  # 4단계 고정 증류 모델. 9B 는 훨씬 비쌈 (D37)
IMAGE_SIZE = 768  # 512 와 지연이 비슷해(둘 다 7~10초) 폰 화면에 맞는 쪽
MAX_SIDE = 2048  # 받은 그림이 이보다 크면 풀기 전에 거절 (디컴프레션 폭탄 — 단일 워커 메모리 보호)
IMAGE_TIMEOUT_SEC = 20  # D36: 초안이 그림을 기다리는 상한
# 화풍·금지 요소는 코드가 고정하고 사물 이름만 끼운다 — 어르신 말은 이 칸으로만 그림 모델에 들어간다.
# 다듬기 담당: 홍진성. 바꾸면 tests/test_diary.py 의 cloudflare 테스트도 확인.
STYLE = (
    "Hand-drawn picture diary illustration in crayon and colored pencil, simple still life of {objects}. "
    "Cream paper background, soft warm pastel colors, naive childlike style, centered, plenty of empty space. "
    "No people, no faces, no hands, no text, no letters, no numbers."
)
# 그릴 사물이 없는 일기는 고른 기분으로 그린다 — 기분 칩 그림 + 작은 사물 하나 (D69, 11/14 사용자:
# 해·꽃 / 구름·풀잎 / 우산·빗방울 / 달·별). 이름은 영어 — 한국어 이름을 넣으니 그림에 글자가 섞였다(11/14 실측).
MOOD_OBJECTS = {
    "SUNNY": ["sun", "flower"],
    "CLOUDY": ["cloud", "blades of grass"],
    "RAINY": ["umbrella", "raindrops"],
    "MOON": ["crescent moon", "stars"],
}


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


def _cloudflare(objects: list[str], seed: int) -> bytes:
    """Workers AI REST 1회 (재시도 없음 — 20초 안에 끝나야 해서). 실패는 예외로 → 부른 쪽이 글만 게시."""
    if not (settings.CF_ACCOUNT_ID and settings.CF_API_TOKEN):
        raise RuntimeError("IMAGE_PROVIDER=cloudflare 인데 CF_ACCOUNT_ID/CF_API_TOKEN 이 비어 있음 (.env)")
    names = ", ".join(" ".join(o.split()) for o in objects[:3])  # 줄바꿈 등 공백은 한 칸으로
    fields = {"prompt": STYLE.format(objects=names), "width": IMAGE_SIZE, "height": IMAGE_SIZE, "seed": seed}
    r = httpx.post(
        f"https://api.cloudflare.com/client/v4/accounts/{settings.CF_ACCOUNT_ID}/ai/run/{CF_MODEL}",
        headers={"Authorization": f"Bearer {settings.CF_API_TOKEN}"},
        files={k: (None, str(v)) for k, v in fields.items()},  # 이 모델은 multipart/form-data 만 받는다
        timeout=IMAGE_TIMEOUT_SEC,
    )
    if r.is_error:  # 401 키 오류 · 429 하루 무료 한도 초과(Workers Free 플랜) · 5xx — 원인 구분용, 본문은 안 남김
        log.warning("image cloudflare status=%d", r.status_code)
    r.raise_for_status()
    img = Image.open(io.BytesIO(base64.b64decode(r.json()["result"]["image"])))  # 머리만 읽음, 아직 안 풂
    if max(img.size) > MAX_SIDE:
        raise ValueError(f"그림이 너무 큼 {img.size}")
    buf = io.BytesIO()
    # 외부에서 받은 바이트를 그대로 저장하지 않는다: 다시 인코딩하면 그림이 아닌 응답은 여기서 예외,
    # 메타데이터가 빠지고 크기는 1/4 쯤(380KB → 80KB)
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return buf.getvalue()


def generate(draw_spec: dict[str, Any], seed: int = 0) -> bytes | None:
    provider = settings.IMAGE_PROVIDER
    t0 = time.perf_counter()
    try:
        if provider == "mock":
            return _placeholder(draw_spec, seed) if settings.is_dev else None
        if provider == "cloudflare":
            objects = draw_spec.get("objects") or []
            return _cloudflare(objects, seed) if objects else None
        raise NotImplementedError(f"IMAGE_PROVIDER={provider} 는 아직 없습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("image provider=%s ms=%d seed=%d", provider, ms, seed)
