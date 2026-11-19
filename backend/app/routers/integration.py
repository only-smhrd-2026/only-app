"""꼬마심심이 연동 (FR-API-001~003): 방장의 연동 동의, 기업 서버가 부르는 주간 요약.

- 밖으로 나가는 것은 schemas/integration.py 에 적힌 숫자와 기분 값뿐이다. 사진·일기·음성·질문과 답의 원문은
  어떤 설정에서도 나가지 않는다.
- 기본값은 꺼짐: INTEGRATION_API_KEY 가 비어 있으면 요약 주소는 없는 주소처럼 404 (FR-API-003, 계약 확정 전 운영 서버).
- 제공 칸·공용 사용자 ID 체계·인증 방식은 기업 확인 뒤 확정한다 [확인 필요]. 지금 elder 는 가족방 번호(room_id).
"""

import hmac
import logging
from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select

from app.config import INTEGRATION_TREND_WEEKS, TZ, WEEKLY_HOUR, now_kst, settings
from app.deps import DB, CurrentUser, require_owner
from app.errors import ApiError
from app.models import ELDER_SPOKE, FamilyRoom, TalkSession, WeeklySummary
from app.schemas.common import ErrorOut
from app.schemas.integration import (
    IntegrationIn,
    IntegrationMoodDay,
    IntegrationOut,
    IntegrationSummaryOut,
    IntegrationTalkWeek,
)
from app.security import integration_blocked, record_integration_failure

log = logging.getLogger("app.integration")
router = APIRouter(tags=["integration"])

_bearer = HTTPBearer(auto_error=False, description="기업에 따로 전한 연동 키")


@router.patch("/rooms/{room_id}/integration", response_model=IntegrationOut)
def set_integration(room_id: int, body: IntegrationIn, user: CurrentUser, db: DB):
    """연동 범위 변경 — 방장만 (기본 NONE, 동의하면 SUMMARY_ONLY). 사진·일기·음성 원문은 어떤 범위에서도 안 나간다."""
    room = require_owner(room_id, user, db)
    if room.integration_scope != body.integration_scope:  # 같은 값을 다시 보내면(두 번 누르기) 동의 시각은 처음 그대로
        room.integration_scope = body.integration_scope
        room.integration_consent_at = now_kst() if body.integration_scope == "SUMMARY_ONLY" else None
        db.commit()
    return IntegrationOut(
        integration_scope=room.integration_scope,
        integration_consent_at=room.integration_consent_at,
        external_user_id=room.external_user_id,
    )


def _require_key(request: Request, sent: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> None:
    """요약 주소의 문지기. elder·week 모양 검사보다 먼저 돈다 — 꺼져 있으면 무엇을 보내도 404, 키가 틀리면 401."""
    key = settings.INTEGRATION_API_KEY
    if not key:
        raise ApiError(404, "HTTP_404", "Not Found")  # 등록 안 된 주소와 똑같은 답
    ip = request.client.host if request.client else "unknown"
    if integration_blocked(ip):  # 막힌 동안에는 맞는 키도 막는다 — 틀린 키만 막으면 계속 맞혀 볼 수 있다
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "잠시 후 다시 시도해 주세요")
    if sent is None or not hmac.compare_digest(sent.credentials.encode(), key.encode()):
        record_integration_failure(ip)
        raise ApiError(401, "INTEGRATION_KEY_INVALID", "연동 키가 올바르지 않습니다")


@router.get(
    "/integration/summary",
    response_model=IntegrationSummaryOut,
    dependencies=[Depends(_require_key)],
    summary="어르신 한 분의 주간 요약 (꼬마심심이 연동)",
    responses={
        401: {"model": ErrorOut, "description": "`INTEGRATION_KEY_INVALID` — 연동 키가 없거나 틀림"},
        404: {
            "model": ErrorOut,
            "description": "`ELDER_NOT_FOUND` — 없는 어르신이거나 연동에 동의하지 않음(둘을 구분하지 않는다) · "
            "`NO_SUMMARY` — 그 주 집계가 아직 없음 · `HTTP_404` — 이 서버에서 연동이 꺼져 있음",
        },
        422: {"model": ErrorOut, "description": "`VALIDATION` — elder·week 모양이 맞지 않거나 week 가 월요일이 아님"},
        429: {
            "model": ErrorOut,
            "description": "`TOO_MANY_ATTEMPTS` — 같은 IP 에서 키가 여러 번 틀림. 풀릴 때까지는 맞는 키도 막힌다",
        },
    },
)
def get_summary(
    db: DB,
    # 범위는 DB BIGINT 와 같게 — 더 큰 수는 DB 오류(500)가 아니라 422
    elder: int = Query(ge=1, le=2**63 - 1, description="어르신 번호. 지금은 가족방 번호(room_id)"),
    week: date = Query(description="그 주 월요일, YYYY-MM-DD (한국 시간)"),
):
    """어르신 한 분의 한 주를 숫자와 기분 값으로만 돌려준다 (FR-API-002).

    - 사진·일기·음성·질문과 답의 원문, 이름·호칭은 어떤 설정에서도 나가지 않는다 (FR-API-001).
    - 방장이 가족방에서 `SUMMARY_ONLY` 로 동의한 어르신만 답한다. 동의를 거두면 바로 404.
    - 인증은 `Authorization: Bearer <연동 키>`. 서버에 키를 넣지 않으면(기본값) 이 주소는 꺼져 있다 (FR-API-003).
    - `elder` 는 지금은 가족방 번호다. 공용 사용자 ID 체계는 기업 확인 뒤 확정한다 [확인 필요].
    - 한 주는 일요일 19시(한국 시간)에 닫히고 그날 저녁에 한 번 집계한다. `week` 는 그 주 월요일.
    """
    if week.weekday() != 0:
        raise ApiError(422, "VALIDATION", "week 는 그 주 월요일 날짜로 보내 주세요")
    room = db.get(FamilyRoom, elder)
    # 없는 방·닫힌 방·동의하지 않은 방은 같은 답 — 동의하지 않은 방이 있는지도 드러내지 않는다
    if room is None or room.status != "ACTIVE" or room.integration_scope != "SUMMARY_ONLY":
        raise ApiError(404, "ELDER_NOT_FOUND", "연동에 동의한 어르신을 찾을 수 없어요")
    # 주간 집계 줄에서 숫자·기분 칸만 읽는다. 질문과 답(qa_list)·안부(notes)·일기 목록은 이 주소가 읽지도 않는다
    mine = WeeklySummary.room_id == elder
    summary = db.execute(
        select(WeeklySummary.memory_days, WeeklySummary.diary_days, WeeklySummary.mood_trend).where(
            mine, WeeklySummary.week_start == week
        )
    ).first()
    if summary is None:
        raise ApiError(404, "NO_SUMMARY", "그 주 요약이 아직 없어요")
    trend = db.execute(
        select(WeeklySummary.week_start, WeeklySummary.talk_volume)
        .where(mine, WeeklySummary.week_start.between(week - timedelta(weeks=INTEGRATION_TREND_WEEKS - 1), week))
        .order_by(WeeklySummary.week_start)
    ).all()
    end = datetime.combine(week + timedelta(days=6), time(WEEKLY_HOUR), tzinfo=TZ)  # 집계 창과 같다 (D19)
    sad_talk_count = db.scalar(
        select(func.count())
        .select_from(TalkSession)
        .where(
            TalkSession.room_id == elder,
            TalkSession.started_at >= end - timedelta(days=7),
            TalkSession.started_at < end,
            ELDER_SPOKE,  # 주간 집계와 같은 '기록' 기준 — 어르신이 한 번이라도 말한 대화만
            TalkSession.emotion_flag != "NONE",
            # '가족에게 말하지 마'라고 하신 대화는 밖으로도 세지 않는다.
            # 가족에게는 그런 대화도 위급이면 알리지만(D55 ③) 밖으로는 위급도 뺀다
            TalkSession.private_flag.is_(False),
        )
    )
    log.info("integration summary room=%s week=%s", elder, week)  # 키·내용 없이 (D15)
    return IntegrationSummaryOut(
        elder=elder,
        week_start=week,
        memory_days=summary.memory_days,
        diary_days=summary.diary_days,
        mood_trend=[IntegrationMoodDay(date=day["date"], mood=day["mood"]) for day in summary.mood_trend],
        talk_volume_trend=[
            IntegrationTalkWeek(
                week_start=start, words=volume["words"], turns=volume["turns"], avg_words=volume["avg_words"]
            )
            for start, volume in trend
        ],
        sad_talk_count=sad_talk_count,
        consent_scope=room.integration_scope,
    )
