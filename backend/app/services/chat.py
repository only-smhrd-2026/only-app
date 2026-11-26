"""심심이 잡담 (D106, 11/25 멘토 아이디어) — 잡담 AI(chat_buddy)에 넘길 데이터와 '지난 이야기' 목록.

잡담은 회상·일기와 같은 sessions 표·같은 대화 길(routers/sessions.py)로 다닌다(kind=CHAT). 그래서 기운 없는 날·
위급 알림, 주간 말 수, 다음 날 안부(story_facts)에 잡담도 저절로 들어간다. 여기는 잡담에만 필요한 것:
오늘 하신 것·가족 이름·지난 이야기·날씨를 모아 AI 에 넘기는 데이터, 이어서 하는 지난 잡담, 목록 제목.
로그에 말은 남기지 않는다 (D15).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import story
from app.ai.schemas import plain_jamo
from app.config import CHAT_CONTEXT_TURNS, CHAT_LIST_DAYS, CHAT_LIST_LIMIT, TZ, now_kst, today_kst
from app.models import ELDER_SPOKE, Diary, FamilyRoom, RoomMember, StoryFact, TalkSession, User
from app.routers.mood import check_due
from app.services import picks, weather

WEEKDAYS = "월화수목금토일"
FACTS_MAX = 3  # 잡담에 넘기는 지난 이야기 수
FACT_DAYS = 7  # 최근 이만큼 안에 들은 이야기만
EARLIER_TURNS = 8  # 이어서 하는 지난 잡담에서 넘기는 마지막 말 수
TITLE_MAX = 16  # 제목이 없는 옛 잡담은 어르신 첫 말 앞부분


def _clock(now: datetime) -> str:
    h = now.hour
    part = "오전" if h < 12 else "오후"
    return f"{part} {h % 12 or 12}시 {now.minute}분"


def _time_of_day(h: int) -> str:
    return "아침" if 5 <= h < 11 else "낮" if h < 17 else "저녁" if h < 21 else "밤"


def _today(db: Session, room_id: int) -> dict[str, Any]:
    """오늘 앱에서 하신 것 — 심심이가 일기·가족 소식을 한 번 권할지 정하는 데 쓴다 (프롬프트 15번)."""
    today = today_kst()
    pick = picks.today_pick(db, room_id, today)
    since = datetime.combine(today, time.min, tzinfo=TZ)
    diary = db.scalar(
        select(Diary.diary_id)
        .where(
            Diary.room_id == room_id,
            Diary.author_type == "ELDER",
            Diary.status == "POSTED",
            Diary.posted_at >= since,
        )
        .limit(1)
    )
    unread = db.scalars(
        select(Diary.diary_id).where(
            Diary.room_id == room_id,
            Diary.author_type == "FAMILY",
            Diary.status == "POSTED",
            Diary.elder_read_at.is_(None),
        )
    ).all()
    return {
        "memory_done": bool(pick and pick.status == "COMPLETED"),
        "diary_done": diary is not None,
        "unread_family_news": len(unread),
        "mood_due": check_due(db, room_id),
    }


def _family(db: Session, room_id: int) -> list[str]:
    """어르신이 부르시는 가족 이름 — 호칭(큰딸)이 있으면 호칭, 없으면 이름."""
    rows = db.execute(
        select(RoomMember.nickname, User.name)
        .join(User, User.user_id == RoomMember.user_id)
        .where(RoomMember.room_id == room_id, RoomMember.removed_at.is_(None))
        .order_by(RoomMember.joined_at)
    ).all()
    return [nickname or name for nickname, name in rows]


def _facts(db: Session, room_id: int) -> list[dict[str, str]]:
    """최근 들은 요즘 이야기 (story_facts — 회상·일기·잡담에서 매일 새벽에 뽑는다, D77)."""
    rows = db.scalars(
        select(StoryFact)
        .where(
            StoryFact.room_id == room_id,
            StoryFact.is_active.is_(True),
            StoryFact.kind.in_(story.ASK_KINDS),
            StoryFact.fact_date >= today_kst() - timedelta(days=FACT_DAYS),
            StoryFact.expires_at > now_kst(),
        )
        .order_by(StoryFact.fact_date.desc(), StoryFact.fact_id)
        .limit(FACTS_MAX)
    ).all()
    return [{"heard_on": story.when(f.fact_date), "text": f.fact_text} for f in rows]


def earlier_of(db: Session, room_id: int, session_id: uuid.UUID | str | None) -> TalkSession | None:
    """이어서 할 지난 잡담 — 이 가족방의 잡담만 (다른 방 것은 없는 것처럼)."""
    if not session_id:
        return None
    s = db.get(TalkSession, uuid.UUID(str(session_id)))
    return s if s and s.room_id == room_id and s.kind == "CHAT" else None


def title_of(session: TalkSession) -> str:
    """'지난 이야기' 목록 제목 — 마지막으로 AI 가 붙인 topic, 없으면 어르신 첫 말 앞부분."""
    topic = next((t.get("topic") for t in reversed(session.turns) if t.get("topic")), None)
    if topic:
        return topic
    said = next((t["text"] for t in session.turns if t.get("speaker") == "ELDER"), "")
    return said if len(said) <= TITLE_MAX else said[:TITLE_MAX] + "…"


def data(
    db: Session,
    room: FamilyRoom,
    session: TalkSession,
    closing: bool,
    max_turns: int,
    resume_of: uuid.UUID | None = None,
) -> dict[str, Any]:
    """chat_buddy 프롬프트에 넘기는 JSON 데이터 (프롬프트 '입력' 절과 같은 이름).

    resume_of = 첫 말을 만들 때만 (이어서 한 지난 잡담). 그 뒤 말은 첫 AI 턴에 남긴 resume_of 를 읽는다.
    """
    now = now_kst()
    first = session.turns[0] if session.turns else {}
    earlier = earlier_of(db, room.room_id, resume_of or first.get("resume_of"))
    turns = [{"speaker": t["speaker"], "text": plain_jamo(t["text"])} for t in session.turns]  # ㅋㅋ·ㅇㅇ → 말로 (D112)
    return {
        "elder_name": room.elder_name,
        "elder_honorific": room.elder_honorific,
        "now": f"{now.month}월 {now.day}일 {WEEKDAYS[now.weekday()]}요일 {_clock(now)}",
        "time_of_day": _time_of_day(now.hour),
        "weather": weather.for_region(room.weather_region),
        "today": _today(db, room.room_id),
        "family": _family(db, room.room_id),
        "facts": _facts(db, room.room_id),
        "earlier": (
            {
                "topic": title_of(earlier),
                "turns": [{"speaker": t["speaker"], "text": t["text"]} for t in earlier.turns[-EARLIER_TURNS:]],
            }
            if earlier
            else None
        ),
        # ponytail: 최근 말만 넘긴다(토큰). 긴 잡담의 앞부분을 기억해야 하면 한 줄 요약을 붙인다
        "turns": turns[-CHAT_CONTEXT_TURNS:],
        "turn_no": sum(1 for t in session.turns if t["speaker"] == "AI") + 1,
        "max_turns": max_turns,
        "closing": closing,
    }


def recent(db: Session, room_id: int) -> list[TalkSession]:
    """'지난 이야기' 목록 — 최근 CHAT_LIST_DAYS 일 동안 어르신이 한 번이라도 말한 잡담, 최신 순."""
    return list(
        db.scalars(
            select(TalkSession)
            .where(
                TalkSession.room_id == room_id,
                TalkSession.kind == "CHAT",
                TalkSession.started_at >= now_kst() - timedelta(days=CHAT_LIST_DAYS),
                ELDER_SPOKE,
            )
            .order_by(TalkSession.started_at.desc())
            .limit(CHAT_LIST_LIMIT)
        )
    )
