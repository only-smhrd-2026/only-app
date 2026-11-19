"""꼬마심심이 연동 계약 (FR-API-001·002). 요약은 기업 서버만 부른다 — 화면 쪽 짝(frontend/src/api/types.ts)이 없다.
동의를 켜고 끄는 화면도 아직 없다. 그 화면을 만들 때 IntegrationIn·IntegrationOut 을 types.ts 에도 적는다.

밖으로 나가는 것은 IntegrationSummaryOut 에 적힌 숫자와 기분 값뿐이다. 이름·호칭·말·글·사진·일기 번호는 칸이 없다.
칸을 늘리면 tests/test_integration_summary.py 의 키 집합 검사가 실패한다 — 기업과 계약을 다시 확인한 뒤에만 늘린다.
"""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.diaries import Mood


class IntegrationIn(BaseModel):
    integration_scope: Literal["NONE", "SUMMARY_ONLY"]


class IntegrationOut(BaseModel):
    integration_scope: str
    integration_consent_at: datetime.datetime | None
    external_user_id: str | None


class _Fixed(BaseModel):
    # 적지 않은 칸을 넣으면 오류 — 원문이 실수로 딸려 나가지 않게. 글이 들어갈 수 있는 str 칸도 두지 않는다 (FR-API-001)
    model_config = ConfigDict(extra="forbid")


class IntegrationMoodDay(_Fixed):
    date: datetime.date
    mood: Mood | None = Field(description="그날 어르신 일기의 기분. 일기가 없는 날은 null")


class IntegrationTalkWeek(_Fixed):
    week_start: datetime.date = Field(description="그 주 월요일")
    words: int = Field(description="어르신이 말한 어절 수")
    turns: int = Field(description="어르신이 말한 횟수")
    avg_words: float = Field(description="한 번 말할 때 평균 어절 수")


class IntegrationSummaryOut(_Fixed):
    elder: int = Field(description="요청한 elder 그대로 (지금은 가족방 번호)")
    week_start: datetime.date = Field(description="그 주 월요일 (한국 시간)")
    memory_days: int = Field(description="회상 대화를 한 날 수, 0~7")
    diary_days: int = Field(description="일기를 쓴 날 수, 0~7")
    mood_trend: list[IntegrationMoodDay] = Field(description="그 주 월~일 7칸")
    talk_volume_trend: list[IntegrationTalkWeek] = Field(
        description="그 주까지 최근 4주의 대화량, 옛 주부터. 집계가 없는 주는 빠진다"
    )
    sad_talk_count: int = Field(
        description="그 주 대화 가운데 기운 없음·위급 신호가 있던 대화 수. "
        "어르신이 '가족에게 말하지 마'라고 하신 대화는 세지 않는다"
    )
    consent_scope: Literal["SUMMARY_ONLY"]
