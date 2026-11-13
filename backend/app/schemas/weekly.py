"""주간 이야기 조회 계약. 빈 API의 응답 모양을 유지한다."""

from datetime import date

from pydantic import BaseModel


class WeeklyOut(BaseModel):
    week_start: date
    memory_days: int
    diary_days: int
    qa_list: list[dict]
    recall_check: dict
    mood_trend: list[dict]
    talk_volume: dict
    diaries: list[dict]
    notes: dict | None
