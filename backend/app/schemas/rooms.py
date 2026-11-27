from datetime import datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.config import PLACES

RelationTag = Literal["CHILD", "GRANDCHILD", "OTHER"]
InviteKind = Literal["FAMILY", "ELDER_DEVICE"]


class RoomCreateIn(BaseModel):
    elder_name: str = Field(min_length=1, max_length=10)
    elder_honorific: str = Field(default="어르신", max_length=20)
    relation_tag: RelationTag
    nickname: str | None = Field(default=None, max_length=12)


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    room_id: int
    elder_name: str
    elder_honorific: str
    owner_user_id: int
    memory_time: time
    diary_time: time
    font_size: str
    tts_speed: Decimal
    tts_voice: str  # FEMALE | MALE — 어르신께 들려 드리는 목소리 (D74)
    weather_region: str | None = None  # 어르신 동네 '전남 영광군'·'서울' — 심심이 날씨 (D106·D111). None = 안 정함
    device_input_mode: str  # VOICE | BUTTON — 가족방 설정 화면(GROUP_003)이 지금 값을 보여 준다
    status: str
    elder_photo_key: str | None = Field(default=None, exclude=True)
    is_owner: bool = False
    # 가족 홈 '시작 3단계'·어르신 바꾸기 판 (D70). 사진 수는 기기 링크 조건(사진 3장)과 같은 셈
    photo_count: int = 0
    member_count: int = 0
    device_connected: bool = False  # 어르신 폰이 연결돼 있는지
    # 어르신 폰이 알려 준 권한. 폰이 연결 안 됐으면 None.
    device_perm_mic: bool | None = None
    device_perm_camera: bool | None = None
    device_perm_notification: bool | None = None
    device_last_seen_at: datetime | None = None  # 그 폰이 마지막으로 서버에 온 때 (5분마다 갱신, deps.py)

    @computed_field
    @property
    def elder_photo_url(self) -> str | None:
        """어르신 얼굴 사진 (11/27, 방장이 넣음). 없으면 null — 화면은 이름 첫 글자 동그라미"""
        return f"/api/media/{self.elder_photo_key}" if self.elder_photo_key else None


class MemberOut(BaseModel):
    user_id: int
    name: str  # users.name — 가입·초대 수락 때 정한 이름
    nickname: str | None  # room_members.nickname — 어르신이 부르는 호칭(예: 큰딸). 없으면 null
    relation_tag: RelationTag
    joined_at: datetime
    is_owner: bool  # family_rooms.owner_user_id 와 같은 사람 (room_members 에는 방장 칸이 없다)
    profile_url: str | None = None  # 11/27 내 정보에서 올린 프로필 사진. 없으면 null


class MemberUpdateIn(BaseModel):
    nickname: str | None = Field(default=None, max_length=12)

    @field_validator("nickname", mode="before")
    @classmethod
    def trim_nickname(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class InviteCreateIn(BaseModel):
    kind: InviteKind


class InviteCreatedOut(BaseModel):
    kind: str
    url: str  # 토큰은 # 뒤 (D16). 한 번만 보여 주고 서버는 해시만 저장
    expires_at: datetime


class InviteOut(BaseModel):
    """아직 쓸 수 있는 링크. 종류마다 1개라 kind 가 곧 식별자 (폐기: DELETE /rooms/{id}/invites/{kind}, D38)."""

    kind: str
    expires_at: datetime


class InviteStatusOut(BaseModel):
    kind: str
    elder_name: str
    expires_at: datetime
    valid: bool
    inviter_name: str | None = None  # 11/23 초대한 사람 — 링크를 누가 만들었는지는 저장하지 않아 방장 이름


class InviteAcceptIn(BaseModel):
    token: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=30)  # 있으면 내 이름 갱신 (JOIN_001)
    relation_tag: RelationTag
    nickname: str | None = Field(default=None, max_length=12)


class DeviceConnectIn(BaseModel):
    token: str = Field(min_length=8, max_length=128)


class DeviceOut(BaseModel):
    room_id: int
    elder_name: str
    elder_honorific: str
    perm_mic: bool
    perm_camera: bool
    perm_notification: bool
    input_mode: str


class PermissionsIn(BaseModel):
    perm_mic: bool | None = None
    perm_camera: bool | None = None
    perm_notification: bool | None = None


class OwnerTransferIn(BaseModel):
    """방장 넘기기 (D98). 받을 사람 = 이 가족방의 다른 구성원."""

    user_id: int


class RoomSettingsIn(BaseModel):
    """원격 설정 FR-AD-003. 보낸 칸만 바꾼다."""

    memory_time: time | None = None  # 정각만 — rooms.py가 검사, D44
    diary_time: time | None = None
    font_size: Literal["L", "XL", "XXL"] | None = None
    tts_speed: Literal["0.80", "0.90", "1.00"] | None = None  # RoomOut과 같이 글자로 받는다 (D74)
    tts_voice: Literal["FEMALE", "MALE"] | None = None  # 어르신께 들려 드리는 목소리 (D74)
    weather_region: str | None = None  # 어르신 동네 '전남 영광군'·'서울' (D106·D111). config.PLACES 의 이름만
    device_input_mode: Literal["VOICE", "BUTTON"] | None = None
    elder_name: str | None = Field(default=None, min_length=1, max_length=10)
    elder_honorific: str | None = Field(default=None, min_length=1, max_length=20)

    @field_validator("weather_region")
    @classmethod
    def known_region(cls, value):
        if value is not None and value not in PLACES:
            raise ValueError("동네는 시·도·시·군 목록에서 골라 주세요")
        return value

    @field_validator("elder_name", "elder_honorific", mode="before")
    @classmethod
    def trim_elder_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class RegionOut(BaseModel):
    """가족방 설정 '사시는 동네' 고르기 (D111). towns 가 비면(광역시·세종) 시·도 하나로 고른다."""

    name: str
    towns: list[str]
