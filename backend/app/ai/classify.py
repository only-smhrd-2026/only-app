"""사진 분류 AI-04 (FR-ME-003, D71). 사진 1장 → Claude 비전 1번 → photos 분류 칸 + '보이는 모습' 한 줄(ai_scene).

- 가족 사진(FAMILY): 10분마다 예약 작업(services/scheduler.py)이 분류 전(analyzed_at NULL) 사진을 CLASSIFY_BATCH 장씩.
  오늘의 한 장은 오늘 올린 사진을 고르지 않으므로(services/picks.py) 늦어도 된다. 서버를 다시 켜도 남은 것을 이어 한다.
- 어르신 카메라 사진(ELDER_CAMERA): 일기 대화를 열 때 그 자리에서(routers/sessions.py), CLASSIFY_SYNC_SEC 안에.
- 가족 일기 사진(FAMILY_DIARY)은 분류하지 않는다 — 오늘의 한 장·문제에 안 쓰인다.
- 모델이 답하면 분류 끝(analyzed_at). 거절·검사 실패·파일 없음·깨진 파일 → 분류 끝 + none·확신 0(다시 해도 같다).
  연결 오류·시간 초과·하루 상한(CLASSIFY_PER_DAY)·저장소 오류 → 분류 전 그대로 — 가족 사진은 다음 차례에 다시.
- mock(키 없는 팀원 PC)이면 부르지 않는다: 분류 전 사진은 지금처럼 공통 문제로 간다.
- 로그에는 사진 번호·결과 종류·시간만 (D15 — 보이는 모습·이름표는 남기지 않는다).
"""

from __future__ import annotations

import io
import logging
import time
from decimal import Decimal

from PIL import Image
from sqlalchemy import select

from app.ai import llm
from app.ai.schemas import PhotoLabel
from app.config import CLASSIFY_BATCH, CLASSIFY_IMAGE_SIDE, now_kst, settings
from app.models import Photo
from app.services import storage

log = logging.getLogger("app.ai")
PROMPT_VERSION = "v1"  # 프롬프트·분류 기준을 바꾸면 올린다 — model_version 에 어느 판으로 분류했는지 남는다


def _small_jpeg(data: bytes) -> bytes:
    """긴 변을 CLASSIFY_IMAGE_SIDE 로 줄인 JPEG. 저장본은 올릴 때 이미 다시 만든 JPEG 다 (D17)."""
    img = Image.open(io.BytesIO(data))
    img.thumbnail((CLASSIFY_IMAGE_SIDE, CLASSIFY_IMAGE_SIDE))
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=85)
    return out.getvalue()


def _store(photo: Photo, label: PhotoLabel | None) -> None:
    photo.model_version = f"{settings.LLM_MODEL}/{PROMPT_VERSION}"[:30]
    photo.analyzed_at = now_kst()
    if label is None:  # 쓸 이름표가 없는 '분류 끝' — none 사진. usable 은 비워 둔다(오늘의 한 장에서 빼지 않음)
        photo.activity = photo.category = "none"
        photo.confidence = Decimal("0")
        return
    photo.usable, photo.is_old, photo.season = label.usable, label.is_old, label.season
    photo.activity, photo.category = label.activity, label.category
    photo.confidence = Decimal(f"{label.confidence:.2f}")
    photo.ai_scene = label.scene or None


def classify(photo: Photo, timeout: float | None = None) -> bool:
    """사진 1장을 분류해 칸을 채운다(커밋은 호출자). 분류가 끝났으면 True, 분류 전 그대로면 False."""
    if settings.LLM_PROVIDER == "mock":
        return False
    t0 = time.perf_counter()
    try:
        data = storage.get(photo.object_key)
    except Exception as e:  # 저장소(R2) 연결 문제 — 다음 차례에 다시
        log.warning("classify photo=%s storage error=%s", photo.photo_id, type(e).__name__)
        return False
    label, result = None, "missing"
    if data:
        try:
            image = _small_jpeg(data)
        except Exception:  # 저장본이 깨짐 — Pillow 는 OSError 말고도 여러 예외를 낸다. 다시 해도 같다
            image, result = None, "unreadable"
        if image is not None:
            try:
                label, result = llm.call_json("classify_photo", {}, PhotoLabel, image=image, timeout=timeout), "ok"
            except llm.LlmRefused:
                result = "refused"
            except llm.LlmError as e:  # 연결 오류·시간 초과·하루 상한 — 분류 전 그대로
                log.info("classify photo=%s later error=%s", photo.photo_id, type(e).__name__)
                return False
    _store(photo, label)
    ms = int((time.perf_counter() - t0) * 1000)
    log.info("classify photo=%s result=%s ms=%d", photo.photo_id, result, ms)  # D15: 이름표·모습은 남기지 않는다
    return True


def run_pending(db) -> tuple[int, int]:
    """분류 전 가족 사진을 오래된 것부터 CLASSIFY_BATCH 장. 돌려주는 값 = (분류한 장수, 다음 차례로 남긴 장수).

    실패(연결 오류·상한)가 2번 이어지면 이번 차례는 멈춘다 — 장애 때 사진마다 시간 상한까지 기다리지 않게.
    """
    if settings.LLM_PROVIDER == "mock":
        return 0, 0
    photos = db.scalars(
        select(Photo)
        .where(Photo.source == "FAMILY", Photo.status == "ACTIVE", Photo.analyzed_at.is_(None))
        .order_by(Photo.photo_id)
        .limit(CLASSIFY_BATCH)
    ).all()
    done = fails = 0
    for photo in photos:
        if classify(photo):
            db.commit()
            done, fails = done + 1, 0
        else:
            fails += 1
            if fails >= 2:
                break
    return done, len(photos) - done
