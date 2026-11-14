import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class TodayPickOut(BaseModel):
    pick_id: int
    photo_id: int
    photo_url: str  # /api/media/{key}
    status: str  # PENDING | COMPLETED | SKIPPED | EXPIRED


class PickSkipIn(BaseModel):
    # 화면이 보고 있던 오늘의 한 장. 오늘 것이 아니면 409 PICK_EXPIRED (D45 ④·D65).
    # 배포 전부터 켜 둔 옛 화면은 번호 없이 보낸다 → 지금처럼 오늘 것을 건너뛴다
    pick_id: int | None = None


class PickListenedIn(BaseModel):
    session_id: uuid.UUID | None = None  # 방금 마친 대화 — 그 대화의 사진에 기록한다. 없으면(옛 화면) 오늘 것


class ElderSettingsOut(BaseModel):
    font_size: str
    tts_speed: Decimal
    input_mode: str
    tts_voice: str = "FEMALE"  # FEMALE | MALE — 화면 고정 안내 mp3 도 이 목소리로 (D74)


class ElderVoiceIn(BaseModel):
    """처음 연결 때 어르신이 고른 목소리 (ELDER_CONNECT_001, D74). 가족은 가족방 설정에서 바꾼다."""

    voice: Literal["FEMALE", "MALE"]


class ElderHomeOut(BaseModel):
    greeting: str
    elder_name: str
    elder_honorific: str
    today_pick: TodayPickOut | None
    unread_family_news: int  # 안 들은 가족 일기 수 + 못 들은 가족 이모지가 있으면 1 (D63)
    settings: ElderSettingsOut


class SttOut(BaseModel):
    transcript: str
    confidence: float


class AlbumPhotoOut(BaseModel):
    photo_id: int
    url: str
    taken_at: date | None
    caption: str | None


class AlbumOut(BaseModel):
    photos: list[AlbumPhotoOut]
