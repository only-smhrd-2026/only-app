"""사진 올리기·목록 응답 모양 (FR-ME-001/002/004). 화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.schemas.elder import PhotoGroup


class PhotoOut(BaseModel):
    is_mine: bool = False
    photo_id: int
    url: str
    taken_at: date | None
    taken_year: int | None = None  # 찍은 날이 없을 때 가족이 고른 연도 (11/23)
    caption: str | None
    people_note: str | None
    status: str
    # 가족방 탭 '올린 사진'(GROUP_004)이 쓰는 AI 분류 (D71·D73). 분류 전이면 analyzed=false 이고 ai_* 는 null
    source: str = "FAMILY"  # FAMILY | ELDER_CAMERA | FAMILY_DIARY
    analyzed: bool = False
    usable: bool | None = None  # 분류 AI가 본 오늘의 한 장에 쓸 수 있는지. 분류 전이거나 이름표가 없으면 None
    ai_activity: str | None = None  # 분류 AI 가 본 활동(data/taxonomy.json 의 글자 또는 'none')
    ai_scene: str | None = None  # 분류 AI 가 본 '보이는 모습' 한 줄
    corrected_activity: str | None = None  # 가족이 고친 활동('none' = 맞는 것 없음) — 있으면 AI 활동보다 먼저
    elder_note: str | None = None  # 어르신이 대화에서 이 사진을 바로잡아 주신 내용 한 문장 (FR-ME-009)
    group: PhotoGroup = "ETC"  # 11/23 사진첩 분류 칩 (app/photo_groups.py)
    uploader_name: str | None = None  # 11/23 올린 사람 — 가족 별명(없으면 이름), 어르신 사진이면 '이름 호칭'
    shown: bool = False  # 11/23 어르신께 보여 드렸나(오늘의 한 장으로 나옴·그 사진으로 대화함). false = 기다려요


class PhotoBatchOut(BaseModel):
    upload_batch_id: uuid.UUID
    photos: list[PhotoOut]


class PhotoListOut(BaseModel):
    has_more: bool = False
    photos: list[PhotoOut]
    waiting_count: int = 0  # 11/23 오늘의 한 장으로 아직 안 쓴 가족 사진 수('남은 사진 N장')


class PhotoCorrectIn(BaseModel):
    corrected_activity: str = Field(max_length=20)
