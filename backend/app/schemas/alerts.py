"""위급 알림(가족 홈 긴급 카드) 계약. 화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AlertOut(BaseModel):
    alert_id: int
    kind: Literal["MOOD", "BODY"]  # MOOD 마음 위급(D55), BODY 몸 위급 — 카드의 안내 문장이 다르다
    created_at: datetime
    acked_at: datetime | None  # None = 아직 아무도 [제가 연락했어요]를 누르지 않음
    acked_by_name: str | None
    acked_by_me: bool
