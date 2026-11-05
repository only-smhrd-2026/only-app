"""일기 API 계약 (FR-DI-003~005, FR-FD-001, D36). 모양을 바꾸면 김승희(화면)를 리뷰어로."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Mood = Literal["SUNNY", "CLOUDY", "RAINY", "MOON"]
IllustrationType = Literal["PHOTO", "AI_DRAWING", "NONE"]


class DraftOut(BaseModel):
    """일기 확인 화면(ELDER_DIARY_003)용 초안. 그림까지 기다린 뒤 돌려준다 (D36)."""

    session_id: uuid.UUID
    body: str
    mood: Mood
    photo_id: int | None  # [다시 말할래요] 때 같은 사진으로 새 대화를 열려고
    illustration_type: IllustrationType  # 사진 일기 PHOTO / 그림일기 AI_DRAWING / 그림 실패·사물 없음 NONE(글만)
    illustration_url: str | None  # PHOTO 면 /api/media/{key}
    illustration_b64: str | None  # AI_DRAWING 이면 그림 바이트 (게시 전이라 URL 없음)
    audio_b64: str | None = None  # 본문 + "이대로 올릴까요?" TTS. None 이면 브라우저 speechSynthesis (D5)


class ElderDiaryIn(BaseModel):
    """'네, 올려요'. 본문은 서버가 만든 초안을 그대로 쓴다 (어르신 일기는 수정 불가)."""

    request_id: uuid.UUID  # 멱등 키 (room_id, request_id)
    session_id: uuid.UUID


class DiaryOut(BaseModel):
    diary_id: int
    room_id: int
    author_type: Literal["ELDER", "FAMILY"]
    author_name: str | None  # 어르신 일기면 "순자 할머니", 가족 일기면 가족 이름
    body: str
    mood: Mood
    illustration_type: IllustrationType
    illustration_url: str | None  # /api/media/{key} (사진 또는 그림일기 그림)
    posted_at: datetime
    read_by_elder: bool  # 어르신이 들었는지 (가족 일기용, FR-FD-004)
    read_by_me: bool  # 지금 보는 사람이 봤는지(내가 쓴 것은 true). 가족 홈 '새 일기 N개' 한 줄 (D36)


class DiaryListOut(BaseModel):
    diaries: list[DiaryOut]
