"""가족 홈 마음 카드: 최근 한국 날짜별 활동·기분만 집계한다.

마음 체크는 마지막 결과의 날짜·단계만(점수 없음). 어르신 마음 체크 초대 여부·답 저장(기기 쿠키, D56).
"""

from datetime import datetime, time, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import (
    MOOD_CHECK_DOWN_MIN,
    MOOD_CHECK_EVERY_DAYS,
    MOOD_CHECK_HARD_MIN,
    MOOD_WEEK_DAYS,
    TZ,
    now_kst,
    today_kst,
)
from app.deps import DB, CurrentDevice, CurrentUser, require_member
from app.models import Diary, FamilyRoom, MoodCheck, TalkSession
from app.schemas.common import OkOut
from app.schemas.mood import MoodCheckDueOut, MoodCheckIn, MoodCheckOut, MoodDayOut, MoodWeekOut
from app.services import picks

router = APIRouter(tags=["mood"])


@router.get("/rooms/{room_id}/mood-week", response_model=MoodWeekOut)
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
        # SAD(11/12 전 값)·LOW·RISK 모두 기운 없는 날, D55.
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
    check = db.execute(
        select(MoodCheck.check_date, MoodCheck.level)
        .where(MoodCheck.room_id == room_id)
        .order_by(MoodCheck.check_date.desc())
        .limit(1)
    ).first()
    last_check = MoodCheckOut(check_date=check.check_date, level=check.level) if check else None
    return MoodWeekOut(
        days=days,
        talked_days=sum(day.talked for day in days),
        low_days=sum(day.low for day in days),
        last_check=last_check,
    )


@router.get("/elder/mood-check", response_model=MoodCheckDueOut)
def mood_check_due(device: CurrentDevice, db: DB):
    today = today_kst()
    last = db.scalar(select(func.max(MoodCheck.check_date)).where(MoodCheck.room_id == device.room_id))
    if last and today - last < timedelta(days=MOOD_CHECK_EVERY_DAYS):
        return MoodCheckDueOut(due=False)
    pick = picks.today_pick(db, device.room_id, today)
    return MoodCheckDueOut(due=pick is None or pick.status != "PENDING")


def check_level(total: int) -> str:
    if total >= MOOD_CHECK_HARD_MIN:
        return "HARD"
    if total >= MOOD_CHECK_DOWN_MIN:
        return "DOWN"
    return "USUAL"


@router.post("/elder/mood-check", response_model=OkOut)
def save_mood_check(body: MoodCheckIn, device: CurrentDevice, db: DB):
    total = sum(body.answers)
    db.execute(
        pg_insert(MoodCheck)
        .values(
            room_id=device.room_id,
            check_date=today_kst(),
            answers=body.answers,
            total=total,
            level=check_level(total),
        )
        .on_conflict_do_nothing(constraint="uq_mood_checks_room_id_check_date")
    )
    db.execute(
        update(FamilyRoom)
        .where(FamilyRoom.room_id == device.room_id, FamilyRoom.mood_check_consent_at.is_(None))
        .values(mood_check_consent_at=now_kst())
    )
    db.commit()
    return OkOut()
