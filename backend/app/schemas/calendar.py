"""달력 응답 모양 (11/25 사용자 — 인스타 스토리 보관함처럼).

화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로. 달은 'YYYY-MM' 글자, 날은 한국 날짜.
"""

import datetime as dt

from pydantic import BaseModel

from app.schemas.diaries import DiaryOut


class CalendarDay(BaseModel):
    date: dt.date
    count: int  # 그날 일기 수
    thumb_url: str | None  # 그날 첫 사진(그림) 일기의 그림 — 사진 있는 일기가 없으면 null(화면이 심심이)


class CalendarOut(BaseModel):
    """가족 일기 달력 한 달 (GET /rooms/{id}/calendar) — 어르신 일기·가족 오늘 소식 모두."""

    month: str
    days: list[CalendarDay]  # 일기가 있는 날만, 이른 날 먼저
    prev_month: str | None  # 일기가 있는 바로 앞 달·뒤 달 — 없으면 null
    next_month: str | None


class CalendarDayOut(BaseModel):
    """그날 일기 (GET /rooms/{id}/calendar/{date})."""

    date: dt.date
    diaries: list[DiaryOut]  # 올린 시각 순서(아침 → 저녁)
    prev_date: dt.date | None  # 일기가 있는 전날·다음 날 — 없으면 null
    next_date: dt.date | None


class PastNewsOut(BaseModel):
    """어르신 '지난 가족 소식' 달력 한 달 (GET /elder/family-news/past) — 이미 들은 가족 일기."""

    month: str
    diaries: list[DiaryOut]  # 올린 시각 순서
    prev_month: str | None  # 들은 가족 일기가 있는 바로 앞 달·뒤 달
    next_month: str | None
