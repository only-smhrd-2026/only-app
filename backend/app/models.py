"""db/schema.sql 의 거울 (D1). 테이블 12개. schema.sql 을 바꾸면 여기도 같이 바꾼다.

CHECK 제약·인덱스는 DB(schema.sql)가 원천이라 여기서는 반복하지 않는다. 컬럼·NULL·UNIQUE·FK·기본값만 맞춘다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# 반복되는 타입/기본값
TS = DateTime(timezone=True)
NOW = text("now()")
TRUE = text("true")
FALSE = text("false")


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    login_type: Mapped[str] = mapped_column(String(10))  # TEST | KAKAO | EMAIL
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    kakao_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(30))
    profile_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10), server_default="ACTIVE")  # ACTIVE | WITHDRAWN
    terms_agreed_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    last_login_at: Mapped[datetime | None] = mapped_column(TS)


class FamilyRoom(Base):
    __tablename__ = "family_rooms"
    room_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    elder_name: Mapped[str] = mapped_column(String(10))
    elder_honorific: Mapped[str] = mapped_column(String(20))
    owner_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    memory_time: Mapped[time] = mapped_column(Time, server_default="09:00")
    diary_time: Mapped[time] = mapped_column(Time, server_default="19:00")
    font_size: Mapped[str] = mapped_column(String(5), server_default="XL")  # L | XL | XXL
    tts_speed: Mapped[Decimal] = mapped_column(Numeric(3, 2), server_default="0.85")
    integration_scope: Mapped[str] = mapped_column(String(15), server_default="NONE")
    integration_consent_at: Mapped[datetime | None] = mapped_column(TS)
    external_user_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    status: Mapped[str] = mapped_column(String(10), server_default="ACTIVE")  # ACTIVE | CLOSED
    # 초대 링크 (D38): 종류마다 1개. 사용·폐기 = 만료 시각을 지금으로
    family_invite_hash: Mapped[str | None] = mapped_column(CHAR(64), unique=True)
    family_invite_expires_at: Mapped[datetime | None] = mapped_column(TS)
    elder_invite_hash: Mapped[str | None] = mapped_column(CHAR(64), unique=True)
    elder_invite_expires_at: Mapped[datetime | None] = mapped_column(TS)
    # 어르신 기기 (D38): 가족방당 1대. device_token_hash NULL = 연결 안 됨
    device_token_hash: Mapped[str | None] = mapped_column(CHAR(64), unique=True)
    device_push_token: Mapped[str | None] = mapped_column(String(255))
    device_perm_notification: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    device_perm_mic: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    device_perm_camera: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    device_input_mode: Mapped[str] = mapped_column(String(8), server_default="VOICE")  # VOICE | BUTTON
    device_connected_at: Mapped[datetime | None] = mapped_column(TS)
    device_last_seen_at: Mapped[datetime | None] = mapped_column(TS)


class RoomMember(Base):
    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_room_members_room_id_user_id"),)
    member_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    relation_tag: Mapped[str] = mapped_column(String(12))  # CHILD | GRANDCHILD | OTHER
    nickname: Mapped[str | None] = mapped_column(String(12))
    joined_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    removed_at: Mapped[datetime | None] = mapped_column(TS)


class GroupVocab(Base):
    __tablename__ = "group_vocab"
    __table_args__ = (UniqueConstraint("room_id", "term", name="uq_group_vocab_room_id_term"),)
    vocab_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    term: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(10))  # NAME | HONORIFIC | PLACE
    source: Mapped[str] = mapped_column(String(10))  # MEMBER | UPLOAD | SESSION
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class Photo(Base):
    __tablename__ = "photos"
    __table_args__ = (UniqueConstraint("room_id", "object_key", name="uq_photos_room_id_object_key"),)
    photo_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    upload_batch_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    object_key: Mapped[str] = mapped_column(String(255))
    thumb_key: Mapped[str | None] = mapped_column(String(255))
    taken_at: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(12))  # FAMILY | ELDER_CAMERA | FAMILY_DIARY
    caption: Mapped[str | None] = mapped_column(String(100))
    people_note: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10), server_default="ACTIVE")  # ACTIVE | DELETED
    uploaded_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    # AI 분류 (D38). 분류 전에는 전부 None
    usable: Mapped[bool | None] = mapped_column(Boolean)
    is_old: Mapped[bool | None] = mapped_column(Boolean)
    season: Mapped[str | None] = mapped_column(String(8))  # SPRING | SUMMER | AUTUMN | WINTER | NONE
    activity: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    corrected_activity: Mapped[str | None] = mapped_column(String(20))
    corrected_at: Mapped[datetime | None] = mapped_column(TS)
    model_version: Mapped[str | None] = mapped_column(String(30))
    analyzed_at: Mapped[datetime | None] = mapped_column(TS)  # None = 아직 분류 전


class DailyPick(Base):
    __tablename__ = "daily_picks"
    __table_args__ = (UniqueConstraint("room_id", "pick_date", name="uq_daily_picks_room_id_pick_date"),)
    pick_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    pick_date: Mapped[date] = mapped_column(Date)
    photo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("photos.photo_id"))
    status: Mapped[str] = mapped_column(String(10), server_default="PENDING")  # PENDING|COMPLETED|SKIPPED|EXPIRED
    shown_count: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(TS)
    skipped_at: Mapped[datetime | None] = mapped_column(TS)
    selected_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    completed_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sessions.session_id"))
    listened_at: Mapped[datetime | None] = mapped_column(TS)


class TalkSession(Base):
    """sessions 테이블. (SQLAlchemy 의 Session 과 이름이 겹쳐 TalkSession 으로 부름)"""

    __tablename__ = "sessions"
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    kind: Mapped[str] = mapped_column(String(8))  # MEMORY | ALBUM | DIARY
    pick_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("daily_picks.pick_id"))
    photo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("photos.photo_id"))
    input_mode: Mapped[str] = mapped_column(String(8))  # VOICE | BUTTON
    started_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    ended_at: Mapped[datetime | None] = mapped_column(TS)
    end_reason: Mapped[str | None] = mapped_column(String(12))  # COMPLETED|USER_STOP|NO_RESPONSE|ERROR|LIMIT
    turn_count: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    emotion_flag: Mapped[str] = mapped_column(String(6), server_default="NONE")  # NONE | SAD
    private_flag: Mapped[bool] = mapped_column(Boolean, server_default=FALSE)
    # 턴 배열 (D38). 키는 schema.sql sessions 아래 주석.
    # 고칠 때는 새 리스트를 넣어야 저장된다 (제자리 append 는 감지 안 됨)
    turns: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))


class QuestionBank(Base):
    __tablename__ = "question_bank"
    question_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # 고정 이름표, 출제 기록이 가리킴 (D39)
    qtype: Mapped[str] = mapped_column(String(10))  # REMEMBER | KNOWHOW | THEN_NOW | COMMON
    activity: Mapped[str | None] = mapped_column(String(20))
    category: Mapped[str | None] = mapped_column(String(20))
    prompt_text: Mapped[str] = mapped_column(String(200))
    choices: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True))  # None → SQL NULL (JSON null 아님)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="5")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    created_by: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class StoryFact(Base):
    __tablename__ = "story_facts"
    fact_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sessions.session_id"))
    source_turn_no: Mapped[int] = mapped_column(SmallInteger)  # 이 세션 turns 의 turn_no (D38)
    fact_text: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10))  # EVENT | PLAN | PREFERENCE | CORRECTION
    fact_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=TRUE)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    expires_at: Mapped[datetime] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class Diary(Base):
    __tablename__ = "diaries"
    __table_args__ = (UniqueConstraint("room_id", "request_id", name="uq_diaries_room_id_request_id"),)
    diary_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    author_type: Mapped[str] = mapped_column(String(6))  # ELDER | FAMILY
    author_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sessions.session_id"))
    photo_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("photos.photo_id"))
    body: Mapped[str] = mapped_column(Text)
    mood: Mapped[str] = mapped_column(String(6))  # SUNNY | CLOUDY | RAINY | MOON
    illustration_type: Mapped[str] = mapped_column(String(10))  # PHOTO | AI_DRAWING | NONE
    illustration_key: Mapped[str | None] = mapped_column(String(255))
    draw_spec: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True))  # None → SQL NULL (JSON null 아님)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    posted_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    status: Mapped[str] = mapped_column(String(8), server_default="POSTED")  # POSTED | DELETED
    elder_read_at: Mapped[datetime | None] = mapped_column(TS)  # 어르신 '다 들었어요' (D38)
    family_read_by: Mapped[list[int]] = mapped_column(JSONB, server_default=text("'[]'"))  # '다 봤어요' 가족 id


class WeeklySummary(Base):
    __tablename__ = "weekly_summaries"
    __table_args__ = (UniqueConstraint("room_id", "week_start", name="uq_weekly_summaries_room_id_week_start"),)
    summary_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    week_start: Mapped[date] = mapped_column(Date)
    memory_days: Mapped[int] = mapped_column(SmallInteger)
    diary_days: Mapped[int] = mapped_column(SmallInteger)
    qa_list: Mapped[Any] = mapped_column(JSONB)
    recall_check: Mapped[Any] = mapped_column(JSONB)
    mood_trend: Mapped[Any] = mapped_column(JSONB)
    talk_volume: Mapped[Any] = mapped_column(JSONB)
    diaries: Mapped[Any] = mapped_column(JSONB)
    notes: Mapped[Any | None] = mapped_column(JSONB)
    baseline_talk: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    rule_check_passed: Mapped[bool] = mapped_column(Boolean)
    generated_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    published_at: Mapped[datetime | None] = mapped_column(TS)
    model_version: Mapped[str] = mapped_column(String(30))


class Notification(Base):
    __tablename__ = "notifications"
    notification_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    room_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("family_rooms.room_id"))
    target_type: Mapped[str] = mapped_column(String(6))  # ELDER | FAMILY
    target_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(60))
    body: Mapped[str | None] = mapped_column(String(200))
    link_screen: Mapped[str | None] = mapped_column(String(30))
    sent_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    read_at: Mapped[datetime | None] = mapped_column(TS)
