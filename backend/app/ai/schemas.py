"""LLM 출력 스키마 + 코드 검사 (D14). 모델이 뭐라고 답하든 여기서 걸러야 화면에 나간다.

금지어는 data/banned_words.json (점수·정답·틀리·치매·저하 …). 모든 어르신 턴에 적용 (NFR-DE-003).
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import ROOT

BANNED_WORDS: list[str] = json.loads((ROOT / "data" / "banned_words.json").read_text("utf-8"))["words"]


def check_banned(text: str) -> str:
    hit = [w for w in BANNED_WORDS if w in text]
    if hit:
        raise ValueError(f"금지어 포함: {hit}")
    return text


def question_marks(text: str) -> int:
    return text.count("?") + text.count("？")


def check_text(v: str) -> str:
    v = v.strip()
    if question_marks(v) > 1:
        raise ValueError("질문은 한 번에 하나만 (물음표 ≤ 1)")
    return check_banned(v)


def check_chips(v: list[str]) -> list[str]:
    out = []
    for s in v:
        s = s.strip()
        if not s or len(s) > 12:
            raise ValueError("추천 답변은 1~12자")
        out.append(check_banned(s))
    return out


class CoachReply(BaseModel):
    """회상·일기 코치 한 턴 응답. 한 문장 질문 + 추천 답변 2~3개."""

    # 이 docstring 은 JSON 스키마 description 으로 모델에게도 간다(일기 동무 diary_buddy). 칩 4개인 일기 기분 질문은
    # 모델이 만들지 않는 고정 문장(coach.DIARY_MOOD_QUESTION)이라 여기 상한(3)은 그대로 둔다.
    text: str = Field(min_length=1, max_length=120)
    suggestions: list[str] = Field(default_factory=list, max_length=3)
    question_type: Literal["RECALL", "REMEMBER", "KNOWHOW", "THEN_NOW", "COMMON", "RECHECK", "CLOSING", "NONE"] = (
        "RECALL"
    )
    choice_mode: Literal["CHIPS", "TWO_BUTTONS"] = "CHIPS"

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str) -> str:
        return check_text(v)

    @field_validator("suggestions")
    @classmethod
    def _chip_rules(cls, v: list[str]) -> list[str]:
        return check_chips(v)


class CoachTurn(BaseModel):
    """회상 대화 한 턴. text: 이번에 할 말, suggestions: 어르신이 고를 짧은 답, signal: 어르신 직전 말로 본 상태."""

    # memory_coach 의 모델 출력. question_type·choice_mode 는 모델이 아니라 코드가 정한다(D42) — 지어낸 질문에
    # 문제 이름표(KNOWHOW 등)가 붙어 출제 기록이 섞이거나, API 계약에 없는 값으로 500 이 나지 않게.
    text: str = Field(min_length=1, max_length=120)
    suggestions: list[str] = Field(default_factory=list, max_length=3)
    signal: Literal["NONE", "SAD", "STOP"] = "NONE"  # SAD·STOP 이면 대화를 끝낸다 (FR-AI-005)

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str) -> str:
        return check_text(v)

    @field_validator("suggestions")
    @classmethod
    def _chip_rules(cls, v: list[str]) -> list[str]:
        return check_chips(v)


class DiaryDraft(BaseModel):
    """일기 초안. 어르신이 하신 말만으로 쓴 1인칭 본문(말씀만큼, 최대 5문장), 기분, 그릴 사물(최대 3개)."""

    # FR-DI-003/005. docstring 은 스키마 description 으로 모델에게 가므로 모델이 읽을 말로 적는다.

    body: str = Field(min_length=1, max_length=400)
    mood: Literal["SUNNY", "CLOUDY", "RAINY", "MOON"]
    # 그림일기에 그릴 사물 최대 3개 (사람·얼굴·건물·특정 장소·글자 제외). 비면 그림 없이 글만
    draw_objects: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("body")
    @classmethod
    def _body_rules(cls, v: str) -> str:
        return check_banned(v.strip())

    @field_validator("draw_objects")
    @classmethod
    def _object_rules(cls, v: list[str]) -> list[str]:
        out = [s.strip() for s in v if s.strip()]
        if any(len(s) > 20 for s in out):
            raise ValueError("그릴 사물은 20자 이내")
        return out
