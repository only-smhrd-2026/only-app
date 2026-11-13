"""화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.config import MOOD_CHECK_QUESTIONS
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


class MoodCheckIn(BaseModel):
    # 문항 순서대로 0~3 — 없었어요·며칠·절반 넘게·거의 매일
    answers: list[Annotated[int, Field(ge=0, le=3)]] = Field(
        min_length=MOOD_CHECK_QUESTIONS, max_length=MOOD_CHECK_QUESTIONS
    )
