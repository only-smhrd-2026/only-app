"""사진 올리기·목록 응답 모양 (FR-ME-001/002/004). 화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

import uuid
from datetime import date

from pydantic import BaseModel, Field


class PhotoOut(BaseModel):
    photo_id: int
    url: str
    taken_at: date | None
    caption: str | None
    people_note: str | None
    status: str


class PhotoBatchOut(BaseModel):
    upload_batch_id: uuid.UUID
    photos: list[PhotoOut]


class PhotoListOut(BaseModel):
    photos: list[PhotoOut]


class PhotoCorrectIn(BaseModel):
    corrected_activity: str = Field(max_length=20)
