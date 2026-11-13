"""화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.diaries import Mood


class MoodDayOut(BaseModel):
    date: datetime.date
    talked: bool
    diary_mood: Mood | None
    low: bool


class MoodCheckOut(BaseModel):
    check_date: datetime.date
    level: Literal["USUAL", "DOWN", "HARD"]


class MoodWeekOut(BaseModel):
    days: list[MoodDayOut]
    talked_days: int
    low_days: int
    last_check: MoodCheckOut | None


class MoodCheckDueOut(BaseModel):
    """True면 어르신 홈에 마음 체크 초대를 띄운다. [다음에]는 기기에서만 기억."""

    due: bool
