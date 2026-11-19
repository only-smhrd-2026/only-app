"""이야기 기억 AI-07 (#46, FR-AI-007·008, D77) — 지난 대화의 '하실 일·하신 일'을 회상 대화 첫 질문으로 잇는다.

- 뽑기(run·extract): 새벽 예약 작업(STORY_HOUR)이 어제 어르신이 말한 가족방마다 그날 대화를 AI 1번에 넘긴다.
  질문·답 쌍과 인용 구절 대조는 주간 요약과 같다(ai/weekly.pairs_of·_squeeze, D62).
  구절이 답 원문에 없으면 그 기억만 버린다.
- 넣지 않는 대화: '가족에게 말하지 마'(private_flag), 기운 없음·슬픔·위급(emotion_flag).
  넣지 않는 답: 음성 인식 신뢰도 WEEKLY_STT_MIN 미만, SAID_MIN 자 미만, 어제 이야기 질문에 한 답 (weekly.pairs_of).
- 고르기(pick): 최근 STORY_LOOKBACK_DAYS 일 안에서 기억이 있는 가장 최근 날의, 아직 안 물은 기억 하나.
  할 일(PLAN) 먼저. 가족방마다 하루 한 번만 묻고, 물은 기억(used_at)은 다시 묻지 않는다.
- '그런 말 안 했어'(deny): 그 기억을 끈다(is_active=false). 주간 이야기 카드에서도 그 답을 뺀다 (ai/weekly.summarize).
- 사진 바로잡기(CORRECTION, FR-ME-009): "김장이 아니라 고사리야"처럼 사진 내용을 바로잡아 주신 답은 같은 AI 호출에서
  따로 뽑아 그 사진에 적는다(photos.elder_note) — 다음 대화는 AI 가 본 모습 대신 그 말을 따르고, 그 사진에는 활동
  문제를 다시 내지 않는다(corrected_activity 'none'). 안부로 이어 묻지 않는다(pick 은 PLAN·EVENT 만).
  주간 이야기에는 정정 문장 카드로 나간다 (ai/weekly.summarize).
- 로그에 어르신 말을 남기지 않는다 (D15) — 개수만.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.ai import llm
from app.ai.schemas import BANNED_WORDS, StoryFactItem, StoryFactItems
from app.ai.weekly import QUOTE_MIN, _squeeze, pairs_of
from app.config import STORY_FACTS_MAX, STORY_KEEP_DAYS, STORY_LOOKBACK_DAYS, TZ, now_kst, today_kst
from app.models import ELDER_SPOKE, Photo, StoryFact, TalkSession

log = logging.getLogger("app.ai")

FACT_MAX = 60  # 기억 한 문장 글자 수 (story_facts.fact_text 칸은 200)
CORRECTIONS_MAX = 2  # 하루치 대화에서 뽑는 사진 바로잡기 수 — 안부 기억(STORY_FACTS_MAX)과 따로 센다 (FR-ME-009)
ASK_KINDS = ("PLAN", "EVENT")  # 다음 날 안부로 이어 묻는 기억. CORRECTION 은 묻지 않는다


def _start(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=TZ)


def check(items: list[StoryFactItem], pairs: list[dict[str, Any]]) -> list[tuple[dict[str, Any], StoryFactItem, str]]:
    """규칙을 지킨 기억만 (근거 쌍, 모델 항목, 다듬은 문장)으로 돌려준다 — 걸린 것은 그것만 버리고 다시 부르지 않는다.

    구절(quote)이 답 원문에 있다는 것은 '그 말을 하셨다'까지만 보장한다.
    문장이 뜻을 바꾸는 것은 여기서 못 잡는다 (D62 와 같다).
    """
    by_ref = {pair["ref"]: pair for pair in pairs}
    passed: dict[str, tuple[dict[str, Any], StoryFactItem, str]] = {}
    for item in items:
        pair = by_ref.get(item.ref)
        fact, quote = " ".join(item.fact.split()), _squeeze(item.quote)
        if (
            pair is None  # 근거가 된 답이 없다
            or item.ref in passed  # 같은 답에서 두 개
            or len(quote) < QUOTE_MIN
            or quote not in _squeeze(pair["said"])  # 어르신이 하지 않은 말
            or not 0 < len(fact) <= FACT_MAX
            or not fact.rstrip(" .!~").endswith("요")  # 전하는 말투
            or any(word in fact for word in BANNED_WORDS)
            or (item.kind == "CORRECTION" and not pair.get("photo_id"))  # 바로잡을 사진이 없는 대화
        ):
            continue
        passed[item.ref] = (pair, item, fact)
    kept = list(passed.values())
    asks = [k for k in kept if k[1].kind in ASK_KINDS][:STORY_FACTS_MAX]
    return asks + [k for k in kept if k[1].kind == "CORRECTION"][:CORRECTIONS_MAX]


def extract(db: Session, room_id: int, day: date) -> int:
    """그날 대화에서 기억을 뽑아 저장하고 저장한 수를 돌려준다. 그날 기억이 이미 있으면(작업이 다시 돎) 하지 않는다.

    끝난 표시(ended_at)는 보지 않는다 — 뒤로 키로 나간 채 둔 대화는 표시 없이 끝나고, 새벽이면 어제 대화는 다 끝났다.
    """
    if db.scalar(select(StoryFact.fact_id).where(StoryFact.room_id == room_id, StoryFact.fact_date == day).limit(1)):
        return 0
    start = _start(day)
    sessions = db.scalars(
        select(TalkSession)
        .where(
            TalkSession.room_id == room_id,
            TalkSession.started_at >= start,
            TalkSession.started_at < start + timedelta(days=1),
            TalkSession.private_flag.is_(False),
            TalkSession.emotion_flag == "NONE",
            ELDER_SPOKE,
        )
        .order_by(TalkSession.started_at, TalkSession.session_id)
    ).all()
    pairs = pairs_of(list(sessions))
    db.commit()  # AI 를 기다리는 동안 DB 연결을 쥐지 않는다
    if not pairs:
        return 0
    data = {"pairs": [{key: pair[key] for key in ("ref", "question", "said")} for pair in pairs]}
    try:
        out = llm.call_json("story_facts", data, StoryFactItems)
    except llm.LlmError:
        log.info("story extract room=%s pairs=%d failed", room_id, len(pairs))
        return 0
    kept = check(out.facts, pairs)
    expires = _start(day + timedelta(days=STORY_KEEP_DAYS))
    db.add_all(
        StoryFact(
            room_id=room_id,
            session_id=uuid.UUID(pair["session_id"]),
            source_turn_no=pair["turn_no"],
            fact_text=fact,
            kind=item.kind,
            fact_date=day,
            expires_at=expires,
        )
        for pair, item, fact in kept
    )
    for pair, item, fact in kept:
        if item.kind == "CORRECTION":
            _note_photo(db, room_id, pair["photo_id"], fact)
    db.commit()
    log.info("story extract room=%s pairs=%d made=%d kept=%d", room_id, len(pairs), len(out.facts), len(kept))
    return len(kept)


def _note_photo(db: Session, room_id: int, photo_id: int, fact: str) -> None:
    """어르신이 바로잡아 주신 내용을 그 사진에 적는다 (FR-ME-009). 지운 사진·다른 방 사진이면 아무것도 하지 않는다.

    ponytail: 무엇을 바로잡으셨든(장소·사람이어도) 그 사진의 활동 문제를 끈다 — 틀린 활동으로 문제를 내는 것보다
    주제·계절 문제로 물러나는 쪽이 낫다. 가족이 '올린 사진'에서 활동을 다시 고르면 그 값이 쓰인다(routers/photos.py).
    """
    photo = db.get(Photo, photo_id)
    if photo is None or photo.room_id != room_id or photo.status != "ACTIVE":
        return
    photo.elder_note = fact
    photo.elder_noted_at = photo.corrected_at = now_kst()
    photo.corrected_activity = "none"  # quiz.photo_tags: 'none' 이면 AI 가 붙인 활동으로 되돌아가지 않는다


def run(db: Session, day: date) -> tuple[int, int]:
    """새벽 예약 작업 — 보관 기간이 지난 기억을 지우고, 그날 어르신이 말한 가족방마다 extract.

    → (방 수, 저장한 기억 수). 방 하나가 실패해도 나머지 방은 계속한다.
    ponytail: 서버가 그 시각에 꺼져 있었으면 그날 것은 건너뛴다. 놓친 날을 채워야 하면 여기서.
    """
    db.execute(delete(StoryFact).where(StoryFact.expires_at < now_kst()))
    db.commit()
    start = _start(day)
    room_ids = db.scalars(
        select(TalkSession.room_id)
        .where(TalkSession.started_at >= start, TalkSession.started_at < start + timedelta(days=1), ELDER_SPOKE)
        .distinct()
    ).all()
    kept = 0
    for room_id in room_ids:
        try:
            kept += extract(db, room_id, day)
        except Exception as e:  # 예외 글에는 어르신 말이 섞일 수 있어 이름만 남긴다 (D15)
            db.rollback()
            log.warning("story extract failed room=%s type=%s", room_id, type(e).__name__)
    return len(room_ids), kept


def pick(db: Session, room_id: int) -> StoryFact | None:
    """오늘 첫 회상 대화에서 이어 물을 기억 하나 (FR-AI-008). 오늘 이미 물었거나 물을 것이 없으면 None."""
    today = today_kst()
    if db.scalar(
        select(StoryFact.fact_id).where(StoryFact.room_id == room_id, StoryFact.used_at >= _start(today)).limit(1)
    ):
        return None
    latest = db.scalar(
        select(func.max(StoryFact.fact_date)).where(
            StoryFact.room_id == room_id,
            StoryFact.is_active.is_(True),
            StoryFact.kind.in_(ASK_KINDS),
            StoryFact.fact_date >= today - timedelta(days=STORY_LOOKBACK_DAYS),
            StoryFact.fact_date < today,
        )
    )
    if latest is None:
        return None
    return db.scalars(
        select(StoryFact)
        .where(
            StoryFact.room_id == room_id,
            StoryFact.fact_date == latest,
            StoryFact.is_active.is_(True),
            StoryFact.kind.in_(ASK_KINDS),
            StoryFact.used_at.is_(None),
        )
        .order_by(case((StoryFact.kind == "PLAN", 0), else_=1), StoryFact.fact_id)
    ).first()


def when(fact_date: date) -> str:
    """첫 질문에 넣는 때 — '어제'·'그저께'·'며칠 전'."""
    return {1: "어제", 2: "그저께"}.get((today_kst() - fact_date).days, "며칠 전")


def deny(db: Session, room_id: int, fact_id: int) -> None:
    """'그런 말 안 했어' — 그 기억을 끈다 (FR-AI-008). 다시 묻지 않고, 주간 이야기 카드에서도 그 답을 뺀다."""
    fact = db.get(StoryFact, fact_id)
    if fact is not None and fact.room_id == room_id:
        fact.is_active = False
        log.info("story denied room=%s fact=%s", room_id, fact_id)
