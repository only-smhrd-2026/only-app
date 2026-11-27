"""사진 올리기·목록 응답 모양 (FR-ME-001/002/004). 화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.schemas.elder import PhotoGroup


class PhotoQuote(BaseModel):
    """어르신이 이 사진으로 하신 이야기 — 주간 이야기 카드 그대로(이미 걸러진 질문·전한 말, 11/25)."""

    day: date  # 그 대화 날
    question: str
    answer: str


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
    # 목록의 올린 사람 사진. 어르신 사진이면 가족방에 등록한 얼굴 사진
    uploader_profile_url: str | None = Field(default=None, exclude_if=lambda value: value is None)
    shown: bool = False  # 11/23 어르신께 보여 드렸나(오늘의 한 장으로 나옴·그 사진으로 대화함). false = 기다려요
    # 11/25 사진첩 판(PHOTO_001) — 목록(list_photos)만 채운다
    talked: bool = False  # 어르신이 이 사진으로 말씀하신 대화가 있다 — 사진 칸 말풍선
    quotes: list[PhotoQuote] = Field(default_factory=list)  # 그 이야기의 주간 이야기 카드 — 주간 이야기가 나온 뒤
    diary_id: int | None = None  # 이 사진을 쓴 게시 일기(어르신 일기·가족 오늘 소식) — 판이 그 일기를 보여 준다


class PhotoBatchOut(BaseModel):
    upload_batch_id: uuid.UUID
    photos: list[PhotoOut]


class PhotoListOut(BaseModel):
    has_more: bool = False
    photos: list[PhotoOut]
    waiting_count: int = 0  # 11/23 오늘의 한 장으로 아직 안 쓴 가족 사진 수('남은 사진 N장')


class PhotoNoteIn(BaseModel):
    """사진 한 장 설명 고치기 (D98). 보낸 칸만 바꾸고, null·빈 글이면 지운다.

    검사는 올리기와 같다(routers/photos.py 의 _note·_year).
    """

    caption: str | None = None
    people_note: str | None = None
    taken_year: int | None = None


class PhotoCorrectIn(BaseModel):
    corrected_activity: str = Field(max_length=20)
