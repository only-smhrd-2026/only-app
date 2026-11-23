import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import SPEECH_MAX_CHARS, STT_MAX_CHARS
from app.schemas.diaries import ReplyIn

PhotoGroup = Literal["FAMILY", "TRAVEL", "FOOD", "NATURE", "EVENT", "ETC"]  # app/photo_groups.py 의 칩 (11/23)


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


class ElderSettingsIn(BaseModel):
    """어르신 설정 화면·처음 연결 글자 단계 (11/23). 보낸 칸만 바꾼다. 값 범위는 가족방 설정(RoomSettingsIn)과 같다."""

    font_size: Literal["L", "XL", "XXL"] | None = None
    tts_speed: Literal["0.80", "0.90", "1.00"] | None = None
    tts_voice: Literal["FEMALE", "MALE"] | None = None

    @field_validator("tts_speed", mode="before")
    @classmethod
    def _speed_text(cls, value):
        # 화면 타입이 string | number 라 0.9 처럼 숫자로 와도 받는다 → '0.90'
        return f"{value:.2f}" if isinstance(value, int | float) and not isinstance(value, bool) else value


class ElderVoiceIn(BaseModel):
    """처음 연결 때 어르신이 고른 목소리 (ELDER_CONNECT_001, D74). 가족은 가족방 설정에서 바꾼다."""

    voice: Literal["FEMALE", "MALE"]


class ElderSpeechIn(BaseModel):
    """어르신 화면이 소리로 읽을 글 — 팝업 문장·안내·가족 소식·지난 일기 (D78). 로그에 남기지 않는다 (D15)."""

    text: str = Field(min_length=1, max_length=SPEECH_MAX_CHARS)


class ElderSpeechOut(BaseModel):
    audio_b64: str | None  # 가족방이 고른 목소리 mp3. null 이면 화면이 기기 목소리로 (mock·상한·제공자 장애)


class ElderHomeOut(BaseModel):
    greeting: str
    elder_name: str
    elder_honorific: str
    today_pick: TodayPickOut | None
    unread_family_news: int  # 안 들은 가족 일기 수 + 못 들은 가족 이모지가 있으면 1 (D63)
    settings: ElderSettingsOut
    diary_today: bool = False  # 11/23 오늘 어르신 일기를 올렸나 — 홈 말풍선 순서
    mood_due: bool = False  # 11/23 마음 체크 할 차례 (GET /elder/mood-check 의 due 와 같은 값)


class SttOut(BaseModel):
    transcript: str
    confidence: float


class AlbumPhotoOut(BaseModel):
    photo_id: int
    url: str
    taken_at: date | None
    caption: str | None
    group: PhotoGroup = "ETC"  # 11/23 분류 칩
    source: Literal["FAMILY", "ELDER_CAMERA", "FAMILY_DIARY"] = "FAMILY"
    diary_id: int | None = None  # 어르신 일기 사진이면 그 일기 (D60 바꿈)


class AlbumOut(BaseModel):
    photos: list[AlbumPhotoOut]


class ElderReplyDraftIn(BaseModel):
    """어르신 [말로 답하기] 녹음을 STT 로 바꾼 글 (11/23). 로그에 남기지 않는다 (D15)."""

    transcript: str = Field(min_length=1, max_length=STT_MAX_CHARS)


class ElderReplyDraftOut(BaseModel):
    text: str  # 어르신 말투 한 줄, 40자까지 — 어르신이 확인한 뒤 POST …/reply 로 보낸다


class ElderReplyIn(ReplyIn):
    """어르신이 확인한 한 줄 — 가족 한마디(ReplyIn)와 같은 검사: 한 줄로 만든 뒤 1~40자."""
