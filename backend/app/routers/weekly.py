"""가족방 주간 이야기 조회. AI 요약·게시 전 집계도 조회한다."""

from datetime import date

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import DB, CurrentUser, require_member
from app.errors import ApiError
from app.models import WeeklySummary
from app.schemas.weekly import WeeklyOut

router = APIRouter(prefix="/rooms/{room_id}/weekly", tags=["weekly"])


@router.get("", response_model=WeeklyOut)
def get_weekly(room_id: int, user: CurrentUser, db: DB, week_start: date | None = None):
    require_member(room_id, user, db)
    stmt = select(WeeklySummary).where(WeeklySummary.room_id == room_id)
    if week_start is not None:
        stmt = stmt.where(WeeklySummary.week_start == week_start)
    row = db.scalar(stmt.order_by(WeeklySummary.week_start.desc()).limit(1))
    if row is None:
        raise ApiError(404, "WEEKLY_NOT_FOUND", "아직 주간 이야기가 없어요")
    return WeeklyOut(
        week_start=row.week_start,
        memory_days=row.memory_days,
        diary_days=row.diary_days,
        qa_list=row.qa_list,
        recall_check=row.recall_check,
        mood_trend=row.mood_trend,
        talk_volume=row.talk_volume,
        diaries=row.diaries,
        notes=row.notes,
    )
