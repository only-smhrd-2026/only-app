"""달력 (11/25 사용자 — 인스타 스토리 보관함처럼). 한국 날짜로 나눈다 (D12).

1. GET /rooms/{room_id}/calendar?month=YYYY-MM — 가족 일기 달력(HOME_003): 일기가 있는 날마다 수·첫 사진.
   month 가 없으면 일기가 있는 가장 최근 달. 어르신 일기·가족 오늘 소식 모두.
2. GET /rooms/{room_id}/calendar/{date} — 그날 일기를 올린 시각 순서로 + 일기가 있는 전날·다음 날.
3. GET /elder/family-news/past?month=YYYY-MM — 어르신 '지난 가족 소식' 달력(ELDER_FAMILY_001): 이미 들은 가족 일기.
   읽기만 한다(읽음 표시는 그대로). 옛 '지난 소식 다시 듣기'(?again=1, 최근 5개)를 바꿈.
"""

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.config import DIARY_MONTH_LIMIT, TZ, today_kst
from app.deps import DB, CurrentDevice, CurrentUser, require_member
from app.models import Diary, FamilyRoom
from app.routers.diaries import _rows
from app.schemas.calendar import CalendarDay, CalendarDayOut, CalendarOut, PastNewsOut
from app.schemas.diaries import DiaryOut

router = APIRouter(tags=["calendar"])

Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM. 없으면 가장 최근 달")]
HEARD = (Diary.author_type == "FAMILY", Diary.elder_read_at.is_not(None))  # 어르신이 이미 들은 가족 일기


def _midnight(day: date) -> datetime:
    """그 한국 날짜의 0시."""
    return datetime(day.year, day.month, day.day, tzinfo=TZ)


def _next_month(first: date) -> date:
    return (first.replace(day=28) + timedelta(days=4)).replace(day=1)


def _ym(day: date | None) -> str | None:
    return day.strftime("%Y-%m") if day else None


def _kst_day(at: datetime | None) -> date | None:
    return at.astimezone(TZ).date() if at else None


def _edge(
    db, room_id: int, cond: tuple, *, before: datetime | None = None, after: datetime | None = None
) -> date | None:
    """조건에 맞는 게시 일기 중 before 바로 앞(없으면 가장 최근) 또는 after 부터 가장 이른 것의 한국 날짜."""
    where = [Diary.room_id == room_id, Diary.status == "POSTED", *cond]
    if after is not None:
        return _kst_day(db.scalar(select(func.min(Diary.posted_at)).where(*where, Diary.posted_at >= after)))
    if before is not None:
        where.append(Diary.posted_at < before)
    return _kst_day(db.scalar(select(func.max(Diary.posted_at)).where(*where)))


def _month(db, room: FamilyRoom, month: str | None, cond: tuple, me: int | None):
    """한 달의 일기(올린 시각 순서)와 일기가 있는 앞·뒤 달. month 가 없으면 일기가 있는 가장 최근 달(없으면 이번 달)."""
    if month:
        first = date(int(month[:4]), int(month[5:]), 1)
    else:
        first = (_edge(db, room.room_id, cond) or today_kst()).replace(day=1)
    start, end = _midnight(first), _midnight(_next_month(first))
    # ponytail: 한 달 DIARY_MONTH_LIMIT 개까지 — 넘으면 그 달 앞쪽이 빠진다. 많아지면 날짜별로 나눠 읽기
    rows = _rows(db, room, *cond, Diary.posted_at >= start, Diary.posted_at < end, me=me, limit=DIARY_MONTH_LIMIT)
    prev = _edge(db, room.room_id, cond, before=start)
    after = _edge(db, room.room_id, cond, after=end)
    return first, rows[::-1], prev, after  # _rows 는 최신 먼저


@router.get("/rooms/{room_id}/calendar", response_model=CalendarOut)
def family_calendar(room_id: int, user: CurrentUser, db: DB, month: Month = None):
    require_member(room_id, user, db)  # 로그인 안 함 401, 남의 가족방 404
    first, rows, prev, after = _month(db, db.get(FamilyRoom, room_id), month, (), user.user_id)
    days: dict[date, list[DiaryOut]] = {}
    for diary in rows:
        days.setdefault(_kst_day(diary.posted_at), []).append(diary)
    return CalendarOut(
        month=_ym(first),
        days=[
            CalendarDay(
                date=day,
                count=len(same),
                thumb_url=next((d.illustration_url for d in same if d.illustration_url), None),
            )
            for day, same in days.items()
        ],
        prev_month=_ym(prev),
        next_month=_ym(after),
    )


@router.get("/rooms/{room_id}/calendar/{day}", response_model=CalendarDayOut)
def family_calendar_day(room_id: int, day: date, user: CurrentUser, db: DB):
    require_member(room_id, user, db)
    start, end = _midnight(day), _midnight(day + timedelta(days=1))
    room = db.get(FamilyRoom, room_id)
    rows = _rows(db, room, Diary.posted_at >= start, Diary.posted_at < end, me=user.user_id, limit=DIARY_MONTH_LIMIT)
    return CalendarDayOut(
        date=day,
        diaries=rows[::-1],
        prev_date=_edge(db, room_id, (), before=start),
        next_date=_edge(db, room_id, (), after=end),
    )


@router.get("/elder/family-news/past", response_model=PastNewsOut)
def elder_past_news(device: CurrentDevice, db: DB, month: Month = None):
    first, rows, prev, after = _month(db, db.get(FamilyRoom, device.room_id), month, HEARD, None)
    return PastNewsOut(month=_ym(first), diaries=rows, prev_month=_ym(prev), next_month=_ym(after))
