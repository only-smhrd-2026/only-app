"""문제 은행에서 문제 고르기 (FR-AI-002, D39·D42·D72). 문제는 LLM 이 아니라 이 코드가 고른다.

순서: 노하우(사진 활동) → 떠올리기(사진 주제) → 그때 vs 지금(그 활동 사진용 → 아무 사진용) → 공통.
분류 전·신뢰도 기준(PHOTO_CONF_MIN 0.5) 미만·none 사진은 활동·주제가 없으니 그때 vs 지금(아무 사진용) → 공통만 남는다.
활동·주제가 둘 다 없는 분류된 사진은 계절로 떠올리기 주제를 고른다(봄→봄꽃·여름→여름 과일·겨울→겨울 음식, D72).
최근 14일(한국 날짜)에 쓴 활동·주제(둘 다 없는 문제는 그 code)는 뺀다.
같은 칸 안에서는 최근 90일에 안 낸 문제 → 가장 오래전에 낸 문제 순 (D72 — 전에는 늘 칸의 첫 문제만 나갔다).
다 빠지면 안 낸 것 먼저, 그다음 가장 오래전에 낸 것 (최소 1문제).
가족방이 오늘(한국 날짜) 이미 2문제를 냈으면 내지 않는다. 출제 기록 = AI 턴의 question_code (sessions.turns, D38).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select, text

from app.config import PHOTO_CONF_MIN, QUIZ_PER_DAY, QUIZ_REPEAT_DAYS, QUIZ_ROTATE_DAYS, TZ, now_kst
from app.models import Photo, QuestionBank, TalkSession

log = logging.getLogger("app.ai")
# 활동·주제가 둘 다 없는 분류된 사진의 떠올리기 주제 (D72, 11/14 사용자). 가을은 맞는 주제가 없어 넣지 않는다
SEASON_CATEGORY = {"SPRING": "봄꽃", "SUMMER": "여름 과일", "WINTER": "겨울 음식"}
_NEVER = datetime(1970, 1, 1, tzinfo=TZ)  # 출제 기록이 없는 문제의 '마지막으로 낸 시각' — 가장 먼저 고른다


@dataclass(frozen=True)
class Quiz:
    code: str
    qtype: str  # REMEMBER | KNOWHOW | THEN_NOW | COMMON (응답의 question_type 이 된다)
    prompt_text: str
    choices: list[str] | None  # 2지선다일 때만


# AI 가 쓰는 생각 문제 유형 — 코드가 돌려 정한다(가장 오래 안 낸 유형부터, 같으면 이 순서). 공통(COMMON)은 대체용 (D72)
GEN_TYPES = ("KNOWHOW", "REMEMBER", "THEN_NOW")
GEN_PREFIX = "GEN-"  # AI 가 쓴 문제의 출제 기록 이름표(예 GEN-REMEMBER). 문제 은행 code 모양(RM-…)과 겹치지 않는다


@dataclass(frozen=True)
class QuizPlan:
    """4번째 질문 계획 (D72 섞기). AI 가 qtype 유형으로 사진·대화에 맞춰 쓰고, 코드 검사에 걸리면 fallback 원문."""

    qtype: str  # GEN_TYPES 중 하나
    fallback: Quiz  # 문제 은행에서 규칙으로 고른 문제 (D42 순서·14일·돌려 쓰기·계절)
    example: str  # 그 유형의 문제 은행 예시 문장 — 모델이 말투를 맞추게
    recent: list[str]  # 최근 14일에 낸 생각 문제(그 AI 턴의 말) — 같은 주제를 피하게, 최신 먼저 5개


def code_type(code: str, by_code: dict[str, QuestionBank]) -> str | None:
    """출제 기록 이름표 → 유형. AI 가 쓴 문제는 GEN-유형, 은행 문제는 그 qtype."""
    if code.startswith(GEN_PREFIX):
        return code[len(GEN_PREFIX) :]
    q = by_code.get(code)
    return q.qtype if q else None


def next_type(bank: Sequence[QuestionBank], history: Sequence[tuple[str, datetime]]) -> str:
    """이 가족방에서 가장 오래전에 낸 생각 문제 유형 (안 낸 유형이 먼저) — 노하우·떠올리기·그때 vs 지금을 돌린다."""
    by_code = {q.code: q for q in bank}
    last: dict[str, datetime] = {}
    for c, at in history:
        t = code_type(c, by_code)
        if t in GEN_TYPES:
            last[t] = max(at, last.get(t, at))
    return min(GEN_TYPES, key=lambda t: (last.get(t, _NEVER), GEN_TYPES.index(t)))


def record_code(plan: QuizPlan, text: str) -> str:
    """출제 기록 이름표: 문제 은행 원문으로 나갔으면(끝이 원문) 그 code, AI 가 쓴 문제면 GEN-유형 (D72)."""
    return plan.fallback.code if text.endswith(plan.fallback.prompt_text) else GEN_PREFIX + plan.qtype


def _label(v: str | None) -> str | None:
    """분류 값. 'none'(맞는 값 없음)과 빈 값은 None."""
    return v if v and v != "none" else None


def photo_tags(photo: Photo | None) -> tuple[str | None, str | None]:
    """사진의 (활동, 주제). 분류 전·신뢰도 기준(0.5) 미만이면 둘 다 None. 가족이 고친 활동은 신뢰도와 상관없이 쓴다.
    둘 다 없는 분류된 사진(신뢰도 기준 이상)은 계절 주제 (D72)."""
    if photo is None:
        return None, None
    sure = photo.analyzed_at is not None and photo.confidence is not None and float(photo.confidence) >= PHOTO_CONF_MIN
    # 가족이 고친 값이 'none'(맞는 활동 없음)이면 그것도 정정이다 — AI 가 붙인 활동으로 되돌아가지 않는다 (FR-ME-009)
    if photo.corrected_activity:
        activity = _label(photo.corrected_activity)
    else:
        activity = _label(photo.activity) if sure else None
    category = _label(photo.category) if sure else None
    if sure and activity is None and category is None:
        category = SEASON_CATEGORY.get(photo.season or "")
    return activity, category


def _tiers(bank: Sequence[QuestionBank], activity: str | None, category: str | None) -> list[list[QuestionBank]]:
    """이 사진에 낼 수 있는 문제를 칸별로, 내는 순서대로. priority 는 같은 칸 안에서만 비교한다."""
    tiers = [
        lambda q: q.qtype == "KNOWHOW" and activity is not None and q.activity == activity,
        lambda q: q.qtype == "REMEMBER" and category is not None and q.category == category,
        lambda q: q.qtype == "THEN_NOW" and activity is not None and q.activity == activity,
        lambda q: q.qtype == "THEN_NOW" and q.activity is None,
        lambda q: q.qtype == "COMMON",
    ]
    active = [q for q in bank if q.is_active]
    return [sorted(filter(match, active), key=lambda q: (q.priority, q.question_id)) for match in tiers]


def choose(
    bank: Sequence[QuestionBank],
    activity: str | None,
    category: str | None,
    history: Sequence[tuple[str, datetime]],
    today: date,
) -> QuestionBank | None:
    """history = 이 가족방 최근 90일의 (question_code, 낸 시각). 순수 함수라 DB 없이 테스트한다."""
    if sum(at.date() == today for _, at in history) >= QUIZ_PER_DAY:
        return None
    recent = [c for c, at in history if (today - at.date()).days < QUIZ_REPEAT_DAYS]  # 빼는 규칙은 14일 그대로
    by_code = {q.code: q for q in bank}  # 비활성 문제도 기록 해석에는 쓴다
    used = [by_code[c] for c in recent if c in by_code]
    used_activities = {q.activity for q in used if q.activity}
    used_categories = {q.category for q in used if q.category}
    used_codes = set(recent)
    last: dict[str, datetime] = {}
    for c, at in history:
        last[c] = max(at, last.get(c, at))

    def fresh(q: QuestionBank) -> bool:
        if q.activity or q.category:
            return q.activity not in used_activities and q.category not in used_categories
        return q.code not in used_codes

    def oldest_first(tier: int, q: QuestionBank) -> tuple:  # 안 낸 문제 → 가장 오래전에 낸 문제, 같으면 내는 순서
        return (last.get(q.code, _NEVER), tier, q.priority, q.question_id)

    tiers = _tiers(bank, activity, category)
    for t, tier in enumerate(tiers):
        candidates = [q for q in tier if fresh(q)]
        if candidates:  # 앞 칸이 먼저. 같은 칸 안에서는 돌려 쓴다 (D72)
            return min(candidates, key=lambda q, t=t: oldest_first(t, q))
    pool = [(t, q) for t, tier in enumerate(tiers) for q in tier]
    # 다 빠짐 → 가장 오래전에 낸 것부터 (안 낸 문제가 가장 먼저, 같으면 내는 순서대로)
    return min(pool, key=lambda tq: oldest_first(*tq))[1] if pool else None


def history(db, room_id: int) -> list[tuple[str, datetime, str]]:
    """최근 90일 출제 기록 (code, 낸 시각, 그 AI 턴의 말). 14일은 빼는 규칙, 90일은 돌려 쓰기 (D72).
    세션을 인덱스(room_id, started_at)로 거른 뒤 turns JSON 을 펼친다 (세션당 17칸, D38)."""
    rows = db.execute(
        text(
            "SELECT t->>'question_code', t->>'created_at', t->>'text' FROM sessions s "
            "CROSS JOIN LATERAL jsonb_array_elements(s.turns) AS t "
            "WHERE s.room_id = :room AND s.started_at >= :since AND t->>'question_code' IS NOT NULL"
        ),
        {"room": room_id, "since": now_kst() - timedelta(days=QUIZ_ROTATE_DAYS)},
    ).all()
    return [(code, datetime.fromisoformat(at), said) for code, at, said in rows]


def pick(db, session: TalkSession) -> QuizPlan | None:
    """이 세션 4번째 질문 계획. 문제 은행이 비었거나 오늘 상한이면 None (그 턴은 보통 회상 질문)."""
    past = history(db, session.room_id)
    asked = [(c, at) for c, at, _ in past]
    today = now_kst().date()
    activity, category = photo_tags(db.get(Photo, session.photo_id) if session.photo_id else None)
    bank = db.scalars(select(QuestionBank)).all()
    q = choose(bank, activity, category, asked, today)
    if q is None:
        log.info("quiz pick room=%s none history=%d", session.room_id, len(past))
        return None
    qtype = next_type(bank, asked)
    # 예시는 그 유형에서 이 사진에 가장 맞는 은행 문제(칸 순서) → 없으면 그 유형의 첫 문제
    pool = [b for tier in _tiers(bank, activity, category) for b in tier]
    rest = sorted((b for b in bank if b.is_active), key=lambda b: (b.priority, b.question_id))
    example = next((b.prompt_text for b in [*pool, *rest] if b.qtype == qtype), q.prompt_text)
    recent = [
        said
        for _, at, said in sorted(past, key=lambda p: p[1], reverse=True)
        if (today - at.date()).days < QUIZ_REPEAT_DAYS
    ]
    log.info("quiz pick room=%s type=%s fallback=%s history=%d", session.room_id, qtype, q.code, len(past))  # D15
    return QuizPlan(qtype, Quiz(q.code, q.qtype, q.prompt_text, q.choices), example, recent[:5])
