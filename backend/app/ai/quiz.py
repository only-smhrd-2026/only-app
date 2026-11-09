"""문제 은행에서 문제 고르기 (FR-AI-002, D39·D42). 문제는 LLM 이 아니라 이 코드가 고른다.

순서: 노하우(사진 활동) → 떠올리기(사진 주제) → 그때 vs 지금(그 활동 사진용 → 아무 사진용) → 공통.
분류 전·신뢰도 0.7 미만·none 사진은 활동·주제가 없으니 그때 vs 지금(아무 사진용) → 공통만 남는다.
최근 14일에 쓴 활동·주제(둘 다 없는 문제는 그 code)는 뺀다.
다 빠지면 14일 안에 안 낸 것 먼저, 그다음 가장 오래전에 낸 것 (최소 1문제).
가족방이 오늘(한국 날짜) 이미 2문제를 냈으면 내지 않는다. 출제 기록 = AI 턴의 question_code (sessions.turns, D38).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select, text

from app.config import PHOTO_CONF_MIN, QUIZ_PER_DAY, QUIZ_REPEAT_DAYS, now_kst
from app.models import Photo, QuestionBank, TalkSession

log = logging.getLogger("app.ai")


@dataclass(frozen=True)
class Quiz:
    code: str
    qtype: str  # REMEMBER | KNOWHOW | THEN_NOW | COMMON (응답의 question_type 이 된다)
    prompt_text: str
    choices: list[str] | None  # 2지선다일 때만


def _label(v: str | None) -> str | None:
    """분류 값. 'none'(맞는 값 없음)과 빈 값은 None."""
    return v if v and v != "none" else None


def photo_tags(photo: Photo | None) -> tuple[str | None, str | None]:
    """사진의 (활동, 주제). 분류 전·신뢰도 0.7 미만이면 둘 다 None. 가족이 고친 활동은 신뢰도와 상관없이 쓴다."""
    if photo is None:
        return None, None
    sure = photo.analyzed_at is not None and photo.confidence is not None and float(photo.confidence) >= PHOTO_CONF_MIN
    # 가족이 고친 값이 'none'(맞는 활동 없음)이면 그것도 정정이다 — AI 가 붙인 활동으로 되돌아가지 않는다 (FR-ME-009)
    if photo.corrected_activity:
        activity = _label(photo.corrected_activity)
    else:
        activity = _label(photo.activity) if sure else None
    return activity, (_label(photo.category) if sure else None)


def _pool(bank: Sequence[QuestionBank], activity: str | None, category: str | None) -> list[QuestionBank]:
    """이 사진에 낼 수 있는 문제를 내는 순서대로. priority 는 같은 칸 안에서만 비교한다."""
    tiers = [
        lambda q: q.qtype == "KNOWHOW" and activity is not None and q.activity == activity,
        lambda q: q.qtype == "REMEMBER" and category is not None and q.category == category,
        lambda q: q.qtype == "THEN_NOW" and activity is not None and q.activity == activity,
        lambda q: q.qtype == "THEN_NOW" and q.activity is None,
        lambda q: q.qtype == "COMMON",
    ]
    active = [q for q in bank if q.is_active]
    return [q for match in tiers for q in sorted(filter(match, active), key=lambda q: (q.priority, q.question_id))]


def choose(
    bank: Sequence[QuestionBank],
    activity: str | None,
    category: str | None,
    history: Sequence[tuple[str, datetime]],
    today: date,
) -> QuestionBank | None:
    """history = 이 가족방 최근 14일의 (question_code, 낸 시각). 순수 함수라 DB 없이 테스트한다."""
    if sum(at.date() == today for _, at in history) >= QUIZ_PER_DAY:
        return None
    by_code = {q.code: q for q in bank}  # 비활성 문제도 기록 해석에는 쓴다
    used = [by_code[c] for c, _ in history if c in by_code]
    used_activities = {q.activity for q in used if q.activity}
    used_categories = {q.category for q in used if q.category}
    used_codes = {c for c, _ in history}

    def fresh(q: QuestionBank) -> bool:
        if q.activity or q.category:
            return q.activity not in used_activities and q.category not in used_categories
        return q.code not in used_codes

    pool = _pool(bank, activity, category)
    picked = next((q for q in pool if fresh(q)), None)
    if picked or not pool:
        return picked
    last: dict[str, datetime] = {}
    for c, at in history:
        last[c] = max(at, last.get(c, at))
    # 다 빠짐 → 가장 오래전에 낸 것부터 (안 낸 문제가 가장 먼저, 같으면 내는 순서대로 — min 은 앞의 것을 고른다)
    return min(pool, key=lambda q: (1, last[q.code]) if q.code in last else (0,))


def history(db, room_id: int) -> list[tuple[str, datetime]]:
    """최근 14일 출제 기록. 세션을 인덱스(room_id, started_at)로 거른 뒤 turns JSON 을 펼친다 (세션당 17칸, D38)."""
    rows = db.execute(
        text(
            "SELECT t->>'question_code', t->>'created_at' FROM sessions s "
            "CROSS JOIN LATERAL jsonb_array_elements(s.turns) AS t "
            "WHERE s.room_id = :room AND s.started_at >= :since AND t->>'question_code' IS NOT NULL"
        ),
        {"room": room_id, "since": now_kst() - timedelta(days=QUIZ_REPEAT_DAYS)},
    ).all()
    return [(code, datetime.fromisoformat(at)) for code, at in rows]


def pick(db, session: TalkSession) -> Quiz | None:
    """이 세션에 낼 문제. 문제 은행이 비었거나 오늘 상한이면 None (그 턴은 보통 회상 질문)."""
    past = history(db, session.room_id)
    activity, category = photo_tags(db.get(Photo, session.photo_id) if session.photo_id else None)
    q = choose(db.scalars(select(QuestionBank)).all(), activity, category, past, now_kst().date())
    log.info("quiz pick room=%s code=%s history=%d", session.room_id, q.code if q else None, len(past))  # D15: id 만
    return Quiz(q.code, q.qtype, q.prompt_text, q.choices) if q else None
