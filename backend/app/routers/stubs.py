"""꼬마심심이 연동의 미구현 API (2순위, FR-API-001)."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import CurrentUser
from app.errors import ApiError


def todo(owner: str):
    raise ApiError(501, "NOT_IMPLEMENTED", f"아직 구현 전입니다 (담당: {owner})")


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


routers = [integration]
