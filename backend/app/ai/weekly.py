"""주간 요약 AI-09 (#56, FR-FD-005·006, D62) — 한 주의 회상 대화에서 가족에게 전할 질문·답 카드를 고른다.

summarize(db, room_id, week_start) 가 weekly_summaries 한 줄의 qa_list·notes·rule_check_passed·model_version 을 채운다.
집계(services/weekly.build) 뒤에 예약 작업이 부른다. AI 가 실패해도 예외를 내지 않고, AI 는 한 주에 한 번만 부른다.

- 모델에는 '질문 + 어르신 답' 쌍만 JSON 데이터로 준다 (D14). 모델은 쌍을 고르고(ref) 전달형 한 문장(answer)과
  어르신 말 그대로의 구절(quote)을 낸다. 질문은 모델이 쓰지 않는다 — 대화 원문(AI 턴)을 코드가 그대로 가져온다.
- 규칙 검사는 코드가 카드마다 한다(check). 걸린 카드만 버린다.
- 넣지 않는 대화: '가족에게 말하지 마'(private_flag, D55 ③), 기운 없음·위급(emotion_flag — 내용 없이
  CARE_LINE 한 줄, FR-FD-006), 일기 대화(이번 주 일기는 집계의 diaries 로 따로 보인다).
- 넣지 않는 답: 음성 인식 신뢰도 WEEKLY_STT_MIN 미만, SAID_MIN 자 미만('네'·'몰라').
- 로그에 어르신 말을 남기지 않는다 (D15) — 개수만.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import llm
from app.ai.schemas import BANNED_WORDS, WeeklyCard, WeeklyCards
from app.config import TZ, WEEKLY_CARDS_MAX, WEEKLY_HOUR, WEEKLY_PAIRS_MAX, WEEKLY_STT_MIN, settings
from app.models import ELDER_SPOKE, FamilyRoom, Photo, TalkSession, WeeklySummary

log = logging.getLogger("app.ai")

CARE_LINE = "전화 한 통 드려 보세요."  # 마음 알림(D55 ②)과 같은 말. 대화 내용은 넣지 않는다
SAID_MIN = 4  # 이보다 짧은 답은 카드 후보에서 뺀다
ANSWER_MAX = 60  # 전달형 한 문장의 글자 수
QUOTE_MIN = 4  # 근거 구절의 글자 수 (빈칸은 세지 않는다)


def _squeeze(text: str) -> str:
    """빈칸을 모두 뺀다 — 음성 인식 원문은 띄어쓰기가 들쭉날쭉해서 구절을 견줄 때는 글자만 본다."""
    return re.sub(r"\s+", "", text)


def pairs_of(sessions: list[TalkSession]) -> list[dict[str, Any]]:
    """대화 → 모델에 줄 질문·답 쌍. ref(a1, a2 …)는 모델이 근거를 가리키는 짧은 이름표."""
    pairs: list[dict[str, Any]] = []
    for session in sessions:
        by_no = {turn.get("turn_no"): turn for turn in session.turns}
        for turn in session.turns:
            said = " ".join(str(turn.get("text", "")).split())
            asked = by_no.get(turn.get("reply_to_turn_no"))
            confidence = turn.get("stt_confidence")
            if turn.get("speaker") != "ELDER" or not asked or len(said) < SAID_MIN:
                continue
            if confidence is not None and confidence < WEEKLY_STT_MIN:  # 잘못 들은 말을 가족에게 전하지 않는다
                continue
            pairs.append(
                {
                    "photo_id": session.photo_id,
                    "date": session.started_at.astimezone(TZ).date().isoformat(),
                    "question": str(asked.get("text", "")),
                    "said": said,
                    "session_id": str(session.session_id),
                    "turn_no": turn.get("turn_no"),
                }
            )
    # ponytail: 쌍이 상한을 넘으면 긴 답부터 남긴다(구체적인 이야기일수록 길다). 날짜별로 고르게 뽑아야 하면 여기서
    longest = sorted(range(len(pairs)), key=lambda i: -len(pairs[i]["said"]))[:WEEKLY_PAIRS_MAX]
    return [{"ref": f"a{n}", **pairs[i]} for n, i in enumerate(sorted(longest), 1)]


def check(cards: list[WeeklyCard], pairs: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """모델이 낸 카드 중 규칙을 지킨 것만 (근거 쌍, 전달형 문장)으로 돌려준다 (FR-FD-006).

    걸린 카드는 그 카드만 버린다 — 다시 쓰게 하지 않는다. 구절(quote)이 원문에 있다는 것은
    '그 말을 하셨다'까지만 보장한다. 전달형 문장이 뜻을 바꾸는 것은 여기서 못 잡는다.
    """
    by_ref = {pair["ref"]: pair for pair in pairs}
    passed: dict[str, tuple[dict[str, Any], str]] = {}
    for card in cards:
        pair = by_ref.get(card.ref)
        answer, quote = " ".join(card.answer.split()), _squeeze(card.quote)
        if (
            pair is None  # 근거가 된 답이 없다
            or card.ref in passed  # 같은 답으로 두 장
            or len(quote) < QUOTE_MIN
            or quote not in _squeeze(pair["said"])  # 어르신이 하지 않은 말
            or not 0 < len(answer) <= ANSWER_MAX
            or not answer.rstrip(" .!~").endswith("요")  # 전달형 어미
            or any(word in answer + pair["question"] for word in BANNED_WORDS)
        ):
            continue
        passed[card.ref] = (pair, answer)
    return list(passed.values())[:WEEKLY_CARDS_MAX]


def summarize(db: Session, room_id: int, week_start: date) -> None:
    """그 주 줄에 카드와 안부 한 줄을 채운다. 줄이 없거나 AI 를 이미 불렀으면(성공·실패 모두) 아무것도 하지 않는다."""
    row = db.scalar(
        select(WeeklySummary).where(WeeklySummary.room_id == room_id, WeeklySummary.week_start == week_start)
    )
    if row is None or row.model_version != "none":
        return
    end = datetime.combine(week_start + timedelta(days=6), time(WEEKLY_HOUR), tzinfo=TZ)  # 집계 창과 같다 (D19)
    sessions = db.scalars(
        select(TalkSession)
        .where(
            TalkSession.room_id == room_id,
            TalkSession.started_at >= end - timedelta(days=7),
            TalkSession.started_at < end,
            ELDER_SPOKE,
        )
        .order_by(TalkSession.started_at, TalkSession.session_id)
    ).all()
    # 기운 없음·위급 대화는 내용 없이 한 줄만. 비밀 부탁 대화는 위급일 때만 센다 (D55 ③)
    care = any(s.emotion_flag != "NONE" and (not s.private_flag or s.emotion_flag == "RISK") for s in sessions)
    pairs = pairs_of(
        [s for s in sessions if s.kind in ("MEMORY", "ALBUM") and not s.private_flag and s.emotion_flag == "NONE"]
    )
    photo_ids = {pair["photo_id"] for pair in pairs if pair["photo_id"]}
    photos = db.scalars(select(Photo).where(Photo.photo_id.in_(photo_ids), Photo.status == "ACTIVE")).all()
    photo_urls = {photo.photo_id: f"/api/media/{photo.object_key}" for photo in photos}
    honorific = db.get(FamilyRoom, room_id).elder_honorific
    db.commit()  # AI 를 기다리는 동안(최대 30초) DB 연결을 쥐지 않는다

    cards: list[dict[str, Any]] = []
    made = 0
    if pairs:  # 전할 답이 없는 주는 AI 를 부르지 않는다
        data = {
            "elder_honorific": honorific,
            "pairs": [{key: pair[key] for key in ("ref", "question", "said")} for pair in pairs],
        }
        try:
            out = llm.call_json("weekly_summary", data, WeeklyCards)
        except llm.LlmError:
            row.model_version = "failed"  # 그 주는 숫자만 보인다. 다시 부르지 않는다
        else:
            made = len(out.cards)
            cards = [
                {
                    "photo_id": pair["photo_id"],
                    "photo_url": photo_urls.get(pair["photo_id"]),  # 지운 사진·사진 없는 대화는 None
                    "date": pair["date"],
                    "question": pair["question"],
                    "answer": answer,
                    "session_id": pair["session_id"],
                    "source_turns": [pair["turn_no"]],
                }
                for pair, answer in check(out.cards, pairs)
            ]
            row.qa_list = cards
            row.rule_check_passed = True  # 저장한 카드는 모두 규칙 검사를 통과한 것
            row.model_version = (settings.LLM_MODEL if settings.LLM_PROVIDER == "anthropic" else "mock")[:30]
    row.notes = {"lines": [CARE_LINE]} if care else None
    db.commit()
    log.info(
        "weekly summarize room=%s pairs=%d made=%d kept=%d care=%s version=%s",
        room_id,
        len(pairs),
        made,
        len(cards),
        care,
        row.model_version,
    )
