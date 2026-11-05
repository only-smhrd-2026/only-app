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


class CoachReply(BaseModel):
    """회상 코치 한 턴 응답. 한 문장 질문 + 추천 답변 2~3개."""

    text: str = Field(min_length=1, max_length=120)
    suggestions: list[str] = Field(default_factory=list, max_length=3)
    question_type: Literal["RECALL", "REMEMBER", "KNOWHOW", "THEN_NOW", "RECHECK", "CLOSING", "NONE"] = "RECALL"
    choice_mode: Literal["CHIPS", "TWO_BUTTONS"] = "CHIPS"

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str) -> str:
        v = v.strip()
        if v.count("?") + v.count("？") > 1:
            raise ValueError("질문은 한 번에 하나만 (물음표 ≤ 1)")
        return check_banned(v)

    @field_validator("suggestions")
    @classmethod
    def _chip_rules(cls, v: list[str]) -> list[str]:
        out = []
        for s in v:
            s = s.strip()
            if not s or len(s) > 12:
                raise ValueError("추천 답변은 1~12자")
            out.append(check_banned(s))
        return out
