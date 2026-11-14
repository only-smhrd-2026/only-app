from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class TodayPickOut(BaseModel):
    pick_id: int
    photo_id: int
    photo_url: str  # /api/media/{key}
    status: str  # PENDING | COMPLETED | SKIPPED | EXPIRED


class ElderSettingsOut(BaseModel):
    font_size: str
    tts_speed: Decimal
    input_mode: str


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
