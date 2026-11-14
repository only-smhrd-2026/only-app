"""주간 이야기 조회 계약. 빈 API의 응답 모양을 유지한다."""

from datetime import date

from pydantic import BaseModel


class WeeklyOut(BaseModel):
    week_start: date
    prev_week_start: date | None = None  # 지난 주 이야기가 있으면 그 주 월요일 — ‹ (WEEKLY_001)
    next_week_start: date | None = None  # 다음 주 이야기가 있으면 그 주 월요일 — ›
    memory_days: int
    diary_days: int
    qa_list: list[dict]
    recall_check: dict
    mood_trend: list[dict]
    talk_volume: dict
    diaries: list[dict]  # {diary_id, date, mood, illustration_url} — 그림 주소는 가족 홈 일기 카드와 같음, 없으면 None
    notes: dict | None
