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
from app.models import ELDER_SPOKE, Diary, FamilyRoom, MoodCheck, TalkSession
from app.routers.devices import notify_family
from app.schemas.mood import MoodCheckDueOut, MoodCheckIn, MoodCheckOut, MoodCheckSavedOut, MoodDayOut, MoodWeekOut
from app.services import care, picks

router = APIRouter(tags=["mood"])


@router.get("/rooms/{room_id}/mood-week", response_model=MoodWeekOut)
def mood_week(room_id: int, user: CurrentUser, db: DB):
    require_member(room_id, user, db)
    today = today_kst()
    first = today - timedelta(days=MOOD_WEEK_DAYS - 1)
    since = datetime.combine(first, time.min, tzinfo=TZ)
    talked_dates = set()
    low_dates = set()
    for started_at, emotion_flag, private_flag in db.execute(
        select(TalkSession.started_at, TalkSession.emotion_flag, TalkSession.private_flag).where(
            TalkSession.room_id == room_id, TalkSession.started_at >= since, ELDER_SPOKE
        )
    ):
        day = started_at.astimezone(TZ).date()
        talked_dates.add(day)
        # SAD(11/12 전 값)·LOW·RISK 모두 기운 없는 날. '가족에게 말하지 마'라고 하신 대화는 빼되 위급은 그대로 (D55 ③)
        if emotion_flag != "NONE" and (emotion_flag == "RISK" or not private_flag):
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


@router.post("/elder/mood-check", response_model=MoodCheckSavedOut)
def save_mood_check(body: MoodCheckIn, device: CurrentDevice, db: DB):
    total = sum(body.answers)
    level = check_level(total)
    saved = db.execute(
        pg_insert(MoodCheck)
        .values(
            room_id=device.room_id,
            check_date=today_kst(),
            answers=body.answers,
            total=total,
            level=level,
        )
        .on_conflict_do_nothing(constraint="uq_mood_checks_room_id_check_date")
        .returning(MoodCheck.check_id)
    ).scalar_one_or_none()
    if level == "HARD" and saved is not None:  # 그날 처음 저장될 때만 — 다시 보내도 알림은 1건 (11/19 S9)
        # 가족이 마음 카드를 열어 보지 않아도 알게. 무엇을 답하셨는지·점수는 넣지 않는다.
        # 종류는 '기운 없는 날' 알림과 같이 써서(MOOD_LOW_2D) 같은 주에 '전화 한 통' 알림이 겹치지 않는다 (D55 ②)
        room = db.get(FamilyRoom, device.room_id)
        who = f"{room.elder_name} {room.elder_honorific}"
        body_text = f"{who}께서 마음 체크에서 요즘 많이 힘들다고 답하셨어요. 무엇을 답하셨는지는 전하지 않아요."
        notify_family(db, room.room_id, "MOOD_LOW_2D", "전화 한 통 드려 보세요", body_text, "HOME_001")
    db.execute(
        update(FamilyRoom)
        .where(FamilyRoom.room_id == device.room_id, FamilyRoom.mood_check_consent_at.is_(None))
        .values(mood_check_consent_at=now_kst())
    )
    db.commit()
    # 끝 인사: 높게 답한 문항 하나를 쉬운 말로 받아 드린다 — 점수·단계는 말하지 않는다 (11/19 멘토링)
    return MoodCheckSavedOut(say=care.check_say(body.answers, hard=level == "HARD"))
