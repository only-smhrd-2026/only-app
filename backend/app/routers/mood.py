"""가족 홈 마음 카드: 최근 한국 날짜별 활동·기분만 집계하며 대화·일기 본문은 읽지 않는다."""

from datetime import datetime, time, timedelta

from fastapi import APIRouter
from sqlalchemy import select

from app.config import MOOD_WEEK_DAYS, TZ, today_kst
from app.deps import DB, CurrentUser, require_member
from app.models import Diary, TalkSession
from app.schemas.mood import MoodDayOut, MoodWeekOut

router = APIRouter(prefix="/rooms", tags=["mood"])


@router.get("/{room_id}/mood-week", response_model=MoodWeekOut)
def mood_week(room_id: int, user: CurrentUser, db: DB):
    require_member(room_id, user, db)
    today = today_kst()
    first = today - timedelta(days=MOOD_WEEK_DAYS - 1)
    since = datetime.combine(first, time.min, tzinfo=TZ)
    talked_dates = set()
    low_dates = set()
    for started_at, emotion_flag in db.execute(
        select(TalkSession.started_at, TalkSession.emotion_flag).where(
            TalkSession.room_id == room_id, TalkSession.started_at >= since
        )
    ):
        day = started_at.astimezone(TZ).date()
        talked_dates.add(day)
        if emotion_flag != "NONE":
            low_dates.add(day)
    moods = {}
    for posted_at, mood in db.execute(
        select(Diary.posted_at, Diary.mood)
        .where(
            Diary.room_id == room_id, Diary.author_type == "ELDER", Diary.status == "POSTED", Diary.posted_at >= since
        )
        .order_by(Diary.posted_at, Diary.diary_id)
    ):
        moods[posted_at.astimezone(TZ).date()] = mood
    days = []
    for offset in range(MOOD_WEEK_DAYS):
        day = first + timedelta(days=offset)
        days.append(MoodDayOut(date=day, talked=day in talked_dates, diary_mood=moods.get(day), low=day in low_dates))
    return MoodWeekOut(
        days=days, talked_days=sum(day.talked for day in days), low_days=sum(day.low for day in days), last_check=None
    )
