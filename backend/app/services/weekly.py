"""주간 이야기 숫자·목록 집계 (D19). AI 요약과 게시는 후속 작업이다.

새 주 줄을 만들 때만 가족에게 WEEKLY_READY 1건씩.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import TZ, WEEKLY_HOUR
from app.models import ELDER_SPOKE, Diary, FamilyRoom, TalkSession, WeeklySummary
from app.routers.devices import notify_family


def window(now: datetime) -> tuple[datetime, datetime, date]:
    """지금까지 끝난 가장 최근 일요일 저녁 집계 창과 그 주 월요일을 돌려준다."""
    now = now.astimezone(TZ)
    days = (now.weekday() + 1) % 7
    end = (now - timedelta(days=days)).replace(hour=WEEKLY_HOUR, minute=0, second=0, microsecond=0)
    if end > now:
        end -= timedelta(days=7)
    return end - timedelta(days=7), end, (end - timedelta(days=6)).date()


def build(db: Session, room_id: int, now: datetime) -> None:
    """가족방 집계를 한 번 저장하며 같은 주를 다시 계산해도 처음 결과를 유지한다."""
    start, end, week_start = window(now)
    sessions = db.scalars(
        select(TalkSession).where(
            TalkSession.room_id == room_id, TalkSession.started_at >= start, TalkSession.started_at < end, ELDER_SPOKE
        )
    ).all()
    diaries = db.scalars(
        select(Diary)
        .where(
            Diary.room_id == room_id,
            Diary.author_type == "ELDER",
            Diary.status == "POSTED",
            Diary.posted_at >= start,
            Diary.posted_at < end,
        )
        .order_by(Diary.posted_at, Diary.diary_id)
    ).all()
    memory_dates = {s.started_at.astimezone(TZ).date() for s in sessions if s.kind in ("MEMORY", "ALBUM")}
    moods = {d.posted_at.astimezone(TZ).date(): d.mood for d in diaries}
    words = turns = 0
    for session in sessions:
        if session.private_flag:  # '가족에게 말하지 마'라고 하신 대화는 이야기한 날로만 세고 말 수에서는 뺀다 (D55 ③)
            continue
        for turn in session.turns:
            if turn.get("speaker") == "ELDER":  # 키가 빠진 칸 하나 때문에 그 방 집계 전체가 실패하지 않게
                turns += 1
                words += len(turn.get("text", "").split())
    mood_trend = [
        {"date": (day := week_start + timedelta(days=offset)).isoformat(), "mood": moods.get(day)}
        for offset in range(7)
    ]
    stmt = (
        pg_insert(WeeklySummary)
        .values(
            room_id=room_id,
            week_start=week_start,
            memory_days=min(len(memory_dates), 7),
            diary_days=min(len(moods), 7),
            qa_list=[],
            recall_check={},
            mood_trend=mood_trend,
            talk_volume={"words": words, "turns": turns, "avg_words": round(words / turns, 1) if turns else 0},
            diaries=[
                {"diary_id": d.diary_id, "date": d.posted_at.astimezone(TZ).date().isoformat(), "mood": d.mood}
                for d in diaries
            ],
            rule_check_passed=False,
            model_version="none",
        )
        .on_conflict_do_nothing(constraint="uq_weekly_summaries_room_id_week_start")
        .returning(WeeklySummary.summary_id)
    )
    created = db.execute(stmt).scalar_one_or_none()
    if created is not None:
        room = db.get(FamilyRoom, room_id)
        notify_family(
            db, room_id, "WEEKLY_READY", f"{room.elder_name} 님의 이번 주 이야기가 도착했어요", link="WEEKLY_001"
        )
    db.commit()
