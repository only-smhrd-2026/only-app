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
    # 가족방 탭 '올린 사진'(GROUP_004)이 쓰는 AI 분류 (D71·D73). 분류 전이면 analyzed=false 이고 ai_* 는 null
    source: str = "FAMILY"  # FAMILY | ELDER_CAMERA | FAMILY_DIARY
    analyzed: bool = False
    ai_activity: str | None = None  # 분류 AI 가 본 활동(data/taxonomy.json 의 글자 또는 'none')
    ai_scene: str | None = None  # 분류 AI 가 본 '보이는 모습' 한 줄
    corrected_activity: str | None = None  # 가족이 고친 활동('none' = 맞는 것 없음) — 있으면 AI 활동보다 먼저


class PhotoBatchOut(BaseModel):
    upload_batch_id: uuid.UUID
    photos: list[PhotoOut]


class PhotoListOut(BaseModel):
    photos: list[PhotoOut]


class PhotoCorrectIn(BaseModel):
    corrected_activity: str = Field(max_length=20)
