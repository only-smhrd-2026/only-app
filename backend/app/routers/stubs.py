"""빈 API — 주소와 요청·응답 모양만 있다 (README 9절 "빈 API부터"). 전부 501 을 돌려준다.

담당자가 채울 때 이 파일에서 자기 라우터를 떼어 별도 파일(photos.py, diaries.py …)로 옮기면 된다.
응답 모델 필드는 테이블명세서·요구사항 기준 초안이며, 바꾸면 김승희(화면)를 리뷰어로.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.deps import CurrentUser
from app.errors import ApiError
from app.schemas.diaries import DiaryOut


def todo(owner: str):
    raise ApiError(501, "NOT_IMPLEMENTED", f"아직 구현 전입니다 (담당: {owner})")


# ---------------------------------------------------------------- 사진 (천주웅, FR-ME-001/002/008/009)
photos = APIRouter(prefix="/rooms/{room_id}/photos", tags=["photos (빈 API)"])


# 사진 올리기(POST)·목록(GET)은 routers/photos.py 로 옮김 (박유승, BE-02)


# ---------------------------------------------------------------- 일기 (천주웅, FR-DI-008, FR-FD-002/003)
diaries = APIRouter(tags=["diaries (빈 API)"])


class DiaryCreateIn(BaseModel):
    request_id: uuid.UUID  # 멱등 키 (room_id, request_id)
    body: str = Field(max_length=2000)
    mood: Literal["SUNNY", "CLOUDY", "RAINY", "MOON"]
    photo_id: int | None = None
    session_id: uuid.UUID | None = None
    illustration_type: Literal["PHOTO", "AI_DRAWING", "NONE"] = "NONE"


# 어르신 일기 게시·가족방 일기 목록·가족 열람 기록(POST /diaries/{id}/read)은 routers/diaries.py 에 있다 (D36)


@diaries.post("/rooms/{room_id}/diaries", response_model=DiaryOut, status_code=201)
def post_family_diary(room_id: int, body: DiaryCreateIn, user: CurrentUser):
    todo("천주웅")


# ---------------------------------------------------------------- 주간 (천주웅 배선 / 홍진성 AI, FR-FD-005~007)
weekly = APIRouter(prefix="/rooms/{room_id}/weekly", tags=["weekly (빈 API)"])


class WeeklyOut(BaseModel):
    week_start: date
    memory_days: int
    diary_days: int
    qa_list: list[dict]
    recall_check: dict
    mood_trend: list[dict]
    talk_volume: dict
    diaries: list[dict]
    notes: dict | None


@weekly.get("", response_model=WeeklyOut)
def get_weekly(room_id: int, user: CurrentUser, week_start: date | None = None):
    todo("천주웅")


# ---------------------------------------------------------------- 알림 (천주웅, FR-NT-002~004)
notifications = APIRouter(prefix="/notifications", tags=["notifications (빈 API)"])


class NotificationOut(BaseModel):
    notification_id: int
    room_id: int
    kind: str
    title: str
    body: str | None
    link_screen: str | None
    sent_at: datetime
    read_at: datetime | None


class NotificationListOut(BaseModel):
    notifications: list[NotificationOut]
    unread: int


@notifications.get("", response_model=NotificationListOut)
def list_notifications(user: CurrentUser):
    todo("천주웅")


@notifications.post("/{notification_id}/read", status_code=204)
def read_notification(notification_id: int, user: CurrentUser):
    todo("천주웅")


# ---------------------------------------------------------------- 꼬마심심이 연동 (2순위, FR-API-001)
integration = APIRouter(prefix="/rooms/{room_id}/integration", tags=["integration (빈 API)"])


class IntegrationIn(BaseModel):
    integration_scope: Literal["NONE", "SUMMARY_ONLY"]


class IntegrationOut(BaseModel):
    integration_scope: str
    integration_consent_at: datetime | None
    external_user_id: str | None


@integration.patch("", response_model=IntegrationOut)
def set_integration(room_id: int, body: IntegrationIn, user: CurrentUser):
    """연동 범위 변경 (기본 NONE, 동의 후 SUMMARY_ONLY). 사진·일기·음성 원문은 어떤 범위에서도 안 나간다."""
    todo("담당 미정")


routers = [photos, diaries, weekly, notifications, integration]
