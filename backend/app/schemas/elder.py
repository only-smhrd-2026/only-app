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
    unread_family_news: int
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
