"""주간 이야기 조회 계약. 빈 API의 응답 모양을 유지한다."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class WeeklyChange(BaseModel):
    """'이번 주 달라진 점' 한 줄 — 문장은 서버가 만든다 (services/weekly.changes). 화면 쪽 짝은 api/types.ts."""

    kind: Literal["TALK_DAYS", "TALK_LENGTH", "MOOD", "CHECK", "CARE", "ALERT"]
    text: str
    tone: Literal["calm", "watch"]  # calm 평소 · watch 살펴볼 것


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
    changes: list[WeeklyChange]  # 지난 주들과 견준 변화·그 주 알림 이력. 자료가 모자란 줄은 없다 — 다 없으면 []
