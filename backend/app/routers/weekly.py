"""가족방 주간 이야기 조회. AI 요약·게시 전 집계도 조회한다."""

from datetime import date

from fastapi import APIRouter
from sqlalchemy import func, select

from app.deps import DB, CurrentUser, require_member
from app.errors import ApiError
from app.models import Diary, FamilyRoom, WeeklySummary
from app.routers.diaries import _rows as diary_rows
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
    # 일기 사진 줄(WEEKLY_001, 목업 ⑤): 가족 홈 일기 카드와 같은 그림 주소. 지워진 일기는 None
    ids = [d["diary_id"] for d in row.diaries]
    shown = diary_rows(db, db.get(FamilyRoom, room_id), Diary.diary_id.in_(ids), me=user.user_id)
    urls = {d.diary_id: d.illustration_url for d in shown}
    # ‹ › 지난 주·다음 주 — 그 주 줄이 있을 때만
    week, mine = WeeklySummary.week_start, WeeklySummary.room_id == room_id
    return WeeklyOut(
        prev_week_start=db.scalar(select(func.max(week)).where(mine, week < row.week_start)),
        next_week_start=db.scalar(select(func.min(week)).where(mine, week > row.week_start)),
        week_start=row.week_start,
        memory_days=row.memory_days,
        diary_days=row.diary_days,
        qa_list=row.qa_list,
        recall_check=row.recall_check,
        mood_trend=row.mood_trend,
        talk_volume=row.talk_volume,
        diaries=[{**d, "illustration_url": urls.get(d["diary_id"])} for d in row.diaries],
        notes=row.notes,
    )
