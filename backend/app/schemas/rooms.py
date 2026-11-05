from datetime import datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    status: str
    is_owner: bool = False


class InviteCreateIn(BaseModel):
    kind: InviteKind


class InviteCreatedOut(BaseModel):
    invite_id: int
    kind: str
    url: str  # 토큰은 # 뒤 (D16). 한 번만 보여 주고 서버는 해시만 저장
    expires_at: datetime


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    invite_id: int
    kind: str
    expires_at: datetime
    created_at: datetime


class InviteStatusOut(BaseModel):
    kind: str
    elder_name: str
    expires_at: datetime
    valid: bool


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
