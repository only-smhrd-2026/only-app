"""화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

import datetime

from pydantic import BaseModel

from app.schemas.diaries import Mood


class MoodDayOut(BaseModel):
    date: datetime.date
    talked: bool
    diary_mood: Mood | None
    low: bool


class MoodWeekOut(BaseModel):
    days: list[MoodDayOut]
    talked_days: int
    low_days: int
    last_check: dict | None
