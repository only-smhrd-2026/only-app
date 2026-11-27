"""회상 카드 (D115, 11/27 팀 회의) — 회상 대화가 끝나면 가족용 한두 줄 요약을 만들어 sessions.family_summary 에 적는다.

- 대상: 사진으로 나눈 대화(MEMORY 오늘의 한 장·ALBUM 사진첩)에서
  어르신이 한 번이라도 말씀하신 것, 최근 하루 안에 시작한 것.
  끝난 표시가 있거나, 없으면(앱을 닫음) 시작하고 MEMORY_CARD_IDLE_MIN 분 지난 것.
- 만들지 않음(''): '가족에게 말하지 마'(private_flag)·위급(RISK) 대화 — 가족 홈에 카드가 없다.
- AI 1번(memory_card 프롬프트). 질문·답 쌍은 주간 이야기와 같은 걸름
  (ai/weekly.pairs_of — 거친 말·잘못 들은 말·어제 안부 답 뺌).
  쓸 답이 없거나 모델이 규칙을 어기면(근거 구절이 원문에 없음·길이·말끝·금지어) 내용 없는 한 줄로 — 카드는 그대로 뜬다.
  AI 장애·하루 상한이면 NULL 로 두고 다음 차례에 다시 (하루가 지나면 그만).
- 로그에 어르신 말·요약을 남기지 않는다 (D15) — 개수만.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai import llm
from app.ai.schemas import BANNED_WORDS, MemoryCardText
from app.ai.weekly import QUOTE_MIN, _squeeze, pairs_of
from app.config import MEMORY_CARD_IDLE_MIN, MEMORY_CARD_LOOKBACK_HOURS, MEMORY_CARD_MAX, now_kst
from app.models import ELDER_SPOKE, Photo, TalkSession

log = logging.getLogger("app.ai")

PLAIN = "이 사진을 보며 이야기를 나누셨어요."  # 쓸 답이 없거나 모델 글이 규칙에 걸렸을 때
BATCH = 10  # 한 차례에 요약하는 대화 수 — 남은 것은 다음 차례에


def check(out: MemoryCardText, pairs: list[dict]) -> str:
    """모델 요약이 규칙을 지키면 다듬은 요약, 아니면 PLAIN."""
    summary = " ".join(out.summary.split())
    quote = _squeeze(out.quote)
    if (
        not 0 < len(summary) <= MEMORY_CARD_MAX
        or not summary.rstrip(" .!~").endswith("요")
        or any(word in summary for word in BANNED_WORDS)
        or len(quote) < QUOTE_MIN
        or not any(quote in _squeeze(p["said"]) for p in pairs)  # 어르신이 하지 않은 말
    ):
        return PLAIN
    return summary


def summarize(db: Session, session: TalkSession) -> str | None:
    """요약 한 줄. '' = 카드 없음, None = AI 장애(다음 차례에 다시)."""
    if session.private_flag or session.emotion_flag == "RISK":
        return ""
    pairs = pairs_of([session])
    if not pairs:
        return PLAIN
    caption = db.scalar(select(Photo.caption).where(Photo.photo_id == session.photo_id)) if session.photo_id else None
    data = {"caption": caption or "", "pairs": [{"question": p["question"], "said": p["said"]} for p in pairs]}
    db.commit()  # AI 를 기다리는 동안 DB 연결·잠금을 쥐지 않는다 (story.extract 와 같다)
    try:
        out = llm.call_json("memory_card", data, MemoryCardText)
    except llm.LlmRefused:
        return PLAIN
    except llm.LlmError:
        return None
    return check(out, pairs)


def run_pending(db: Session) -> tuple[int, int]:
    """요약이 아직 없는 회상 대화를 BATCH 개까지 요약한다. (만든 수, 다음 차례로 미룬 수)."""
    now = now_kst()
    ids = db.scalars(
        select(TalkSession.session_id)
        .where(
            TalkSession.kind.in_(["MEMORY", "ALBUM"]),
            TalkSession.family_summary.is_(None),
            TalkSession.started_at >= now - timedelta(hours=MEMORY_CARD_LOOKBACK_HOURS),
            or_(
                TalkSession.ended_at.is_not(None),
                TalkSession.started_at < now - timedelta(minutes=MEMORY_CARD_IDLE_MIN),
            ),
            ELDER_SPOKE,
        )
        .order_by(TalkSession.started_at)
        .limit(BATCH)
    ).all()
    made = later = 0
    for session_id in ids:
        summary = summarize(db, db.get(TalkSession, session_id))
        if summary is None:
            later += 1
            continue
        # 다시 읽어 적는다 — AI 를 기다리는 사이 다른 요청이 이 줄을 바꿨을 수 있다(그 사이 끝난 표시 등)
        db.get(TalkSession, session_id, with_for_update=True).family_summary = summary
        db.commit()  # 하나씩 — 뒤에서 실패해도 앞 카드는 뜬다
        made += 1
    if ids:
        log.info("memory cards made=%d later=%d", made, later)
    return made, later
