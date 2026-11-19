"""돌봄 일지(가족 홈) 계약. 화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로."""

import datetime
from typing import Literal

from pydantic import BaseModel


class CareDayOut(BaseModel):
    """하루치 돌봄 일지. 문장은 서버가 만든다 — 어르신 말 원문·점수는 넣지 않는다."""

    date: datetime.date
    level: Literal["WATCH", "CARE"]  # 지켜봄 / 주의 (평소인 날은 목록에 없다)
    heard: str | None  # 들은 것 — '잠을 잘 못 주무신다고 하셨어요.'
    did: str | None  # 한 일 — '첫인사로 잠 안부를 여쭸어요.'
    reaction: str | None  # 어르신 답 — '괜찮다고 하셨어요.'
    notes: list[str]  # 그 밖에 달라진 점 — '말수가 평소보다 줄었어요.'


class CareOut(BaseModel):
    days: list[CareDayOut]  # 새 날부터, 최근 7일 가운데 살핀 것이 있는 날만
