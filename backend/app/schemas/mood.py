"""화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.diaries import Mood

MoodKind = Literal["PHQ8", "PHQ9", "UCLA3", "GAD7", "SMCQ", "MEMGAME"]
Level = Literal["USUAL", "DOWN", "HARD"]
# 종류별 (칸 수, 화면 값 최댓값) — 각 척도의 원래 보기 칸 수 (11/23). 화면 값은 0부터
# PHQ8·PHQ9·GAD7: 없었어요·며칠·절반 넘게·거의 매일(0~3) · UCLA3: 거의 없어요·가끔·자주(0~2, 공식 점수는 값+1)
# SMCQ: 아니요·네(0~1) · MEMGAME: 낱말 세 개 중 맞힌 수 한 칸(0~3)
MOOD_SHAPE: dict[str, tuple[int, int]] = {
    "PHQ8": (8, 3),
    "PHQ9": (9, 3),
    "UCLA3": (3, 2),
    "GAD7": (7, 3),
    "SMCQ": (14, 1),
    "MEMGAME": (1, 3),
}


class MoodDayOut(BaseModel):
    date: datetime.date
    talked: bool
    diary_mood: Mood | None
    low: bool


class MoodCheckOut(BaseModel):
    check_date: datetime.date
    level: Level


class MoodOtherOut(BaseModel):
    """외로움·걱정·기억력 체크·기억력 놀이의 마지막 결과 — 점수 없이 얼굴·말만 (11/23 사용자)"""

    kind: str
    check_date: datetime.date
    face: str
    title: str


class MoodWeekOut(BaseModel):
    days: list[MoodDayOut]
    talked_days: int
    low_days: int
    last_check: MoodCheckOut | None  # PHQ8·PHQ9 만 (11/23)
    other_checks: list[MoodOtherOut] = []  # 그 밖의 체크, 종류마다 마지막 1개 (11/23 사용자 — 결과만, 알림 없음)
    last_talk_at: datetime.datetime | None = None  # 11/23 마지막 대화 시각(어르신이 말한 대화의 시작)


class MoodCheckDueOut(BaseModel):
    """True면 어르신 홈에 마음 체크 초대를 띄운다. [다음에]는 기기에서만 기억."""

    due: bool


class MoodCheckIn(BaseModel):
    kind: MoodKind = "PHQ8"  # 없으면 마음 체크(PHQ8) — 11/23 전 화면 그대로
    # 문항 순서대로 화면 값. 칸 수·범위는 종류마다 MOOD_SHAPE
    answers: list[Annotated[int, Field(ge=0)]] = Field(min_length=1, max_length=14)

    @model_validator(mode="after")
    def _shape(self):
        size, top = MOOD_SHAPE[self.kind]
        if len(self.answers) != size or any(a > top for a in self.answers):
            raise ValueError(f"{self.kind} 는 {size}칸, 값은 0~{top}")
        return self


class MoodCheckSavedOut(BaseModel):
    ok: bool = True
    # 어르신께 드리는 끝 인사 한마디('잠이 편치 않은 날이 많으셨군요. …'). None 이면 화면이 평소 인사를 한다
    say: str | None = None
    # 11/23 결과 — 점수 없이 얼굴·말 (NFR-DE-003). sub 는 빈 글일 수 있다
    face: str
    title: str
    sub: str


class MoodHistoryItem(BaseModel):
    check_date: datetime.date
    kind: MoodKind
    level: Level
    face: str
    title: str


class MoodHistoryOut(BaseModel):
    items: list[MoodHistoryItem]  # 최신 먼저, 최대 MOOD_HISTORY_LIMIT. 점수 없음
