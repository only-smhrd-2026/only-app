"""일기 API 계약 (FR-DI-003~005, FR-FD-001, D36). 모양을 바꾸면 김승희(화면)를 리뷰어로."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

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


class DiaryCreateIn(BaseModel):
    request_id: uuid.UUID  # 멱등 키 (room_id, request_id)
    body: str = Field(max_length=2000)
    mood: Mood
    photo_id: int | None = None
    session_id: uuid.UUID | None = None
    illustration_type: IllustrationType = "NONE"


class ReactionIn(BaseModel):
    """가족이 어르신 일기에 보내는 이모지 (D54). on = '이 상태로 만들어 줘' — 같은 요청이 두 번 와도 결과가 같다."""

    kind: Literal["HEART", "SMILE", "CLAP"]
    on: bool


class ElderLikeIn(BaseModel):
    """어르신이 가족 일기에 누르는 [좋아요] (D54). 종류가 하나라 on 만."""

    on: bool


class ReactionOut(BaseModel):
    by: Literal["ELDER", "FAMILY"]
    kind: Literal["LIKE", "HEART", "SMILE", "CLAP"]
    user_id: int | None = None  # 가족만
    name: str | None = None  # 가족만 — 가족방 별명, 없으면 이름. 응답에만 있다 (DB 에는 user_id 만)
    at: datetime


class DiaryOut(BaseModel):
    diary_id: int
    room_id: int
    author_type: Literal["ELDER", "FAMILY"]
    author_name: str | None  # 어르신 일기면 "순자 할머니", 가족 일기면 가족 이름
    # 가족 일기를 쓴 사람이 가족방에 들어올 때 정한 별명(예: "큰딸"). 없거나 어르신 일기면 null.
    # 어르신 가족 소식 화면이 "큰딸 ○○" 처럼 관계와 이름을 같이 읽는다 (화면설계서 ELDER_FAMILY_001 ①)
    author_nickname: str | None = None
    body: str
    mood: Mood
    illustration_type: IllustrationType
    illustration_url: str | None  # /api/media/{key} (사진 또는 그림일기 그림)
    posted_at: datetime
    read_by_elder: bool  # 어르신이 들었는지 (가족 일기용, FR-FD-004)
    read_by_me: bool  # 지금 보는 사람이 봤는지(내가 쓴 것은 true). 가족 홈 '새 일기 N개' 한 줄 (D36)
    # 리액션 (D54). 누른 사람마다 1칸 — 가족 HEART·SMILE·CLAP 은 어르신 일기에, 어르신 LIKE 는 가족 일기에.
    # name 은 응답에만 있다
    reactions: list[ReactionOut]


class DiaryListOut(BaseModel):
    diaries: list[DiaryOut]


class HeartOut(BaseModel):
    """어르신이 아직 못 들은 가족 이모지 한 개 — 가족 소식 첫 장 '하트가 왔어요' (D63)."""

    diary_id: int  # 어르신이 쓴 어느 일기에 보냈는지
    kind: Literal["HEART", "SMILE", "CLAP"]
    name: str | None  # 보낸 가족의 가족방 별명, 없으면 이름
    at: datetime


class FamilyNewsOut(DiaryListOut):
    """어르신 가족 소식 (GET /elder/family-news): 안 들은 가족 일기 + 아직 못 들은 가족 이모지(받은 순서)."""

    hearts: list[HeartOut]


class HeartsHeardIn(BaseModel):
    # 읽어 드린 마지막 하트의 at. 그 뒤에 온 하트는 다음에 읽어 드린다. 시간대 없는 시각은 422
    until: AwareDatetime
