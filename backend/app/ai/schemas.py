"""LLM 출력 스키마 + 코드 검사 (D14). 모델이 뭐라고 답하든 여기서 걸러야 화면에 나간다.

금지어는 data/banned_words.json (점수·정답·틀리·치매·저하 …). 모든 어르신 턴에 적용 (NFR-DE-003).
"""

from __future__ import annotations

import json
import math
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import FAMILY_DRAFT_MAX, ROOT

BANNED_WORDS: list[str] = json.loads((ROOT / "data" / "banned_words.json").read_text("utf-8"))["words"]
# 위급 표현 조각 (D55 ① 안전망). 띄어쓰기를 뺀 어르신 말에 들어 있으면 AI 판단과 상관없이 위급으로 본다
RISK_WORDS: list[str] = json.loads((ROOT / "data" / "risk_words.json").read_text("utf-8"))["words"]
# 사진 분류 이름표 (활동·주제 각 20 + 고르는 기준 _rules). 정답표·문제 은행과 같은 글자 (D71)
TAXONOMY: dict = json.loads((ROOT / "data" / "taxonomy.json").read_text("utf-8"))


def has_risk_words(text: str) -> bool:
    t = re.sub(r"\s+", "", text)
    return any(w in t for w in RISK_WORDS)


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


# 모델이 만드는 말의 상한 (D52 ④·⑨, 11/13 사용자). 코드가 정한 고정 문장·고정 답('잘 모르겠어요' 등)에는 걸지 않는다
MODEL_TEXT_MAX = 60  # 한 번에 60자까지. 프롬프트는 50자 안팎을 달라고 해서 넘어 다시 부르는 일이 적게
MODEL_CHIP_MAX = 6  # 추천 답변은 빈칸을 빼고 6자 이내 (384px 화면에 두 개가 한 줄)


def check_model_chips(v: list[str]) -> list[str]:
    out = check_chips(v)
    if any(len(s.replace(" ", "")) > MODEL_CHIP_MAX for s in out):
        raise ValueError(f"추천 답변은 빈칸을 빼고 {MODEL_CHIP_MAX}자 이내")
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
    """회상 대화 한 턴. text: 이번에 할 말, suggestions: 어르신이 고를 짧은 답, signal: 어르신 직전 말로 본 상태,
    private: 어르신이 이 이야기를 가족에게 전하지 말라고 하셨는지."""

    # memory_coach 의 모델 출력. question_type·choice_mode 는 모델이 아니라 코드가 정한다(D42) — 지어낸 질문에
    # 문제 이름표(KNOWHOW 등)가 붙어 출제 기록이 섞이거나, API 계약에 없는 값으로 500 이 나지 않게.
    text: str = Field(min_length=1, max_length=MODEL_TEXT_MAX)
    suggestions: list[str] = Field(default_factory=list, max_length=3)
    # LOW 는 기록하고 이어 감, SAD·RISK·STOP 이면 대화를 끝낸다 (FR-AI-005, D55)
    signal: Literal["NONE", "LOW", "SAD", "RISK", "STOP"] = "NONE"
    private: bool = False  # '애들한테 말하지 마' → 그 대화는 기운 없는 날에서 뺀다. 위급만 예외 (D55 ③)

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str) -> str:
        return check_text(v)

    @field_validator("suggestions")
    @classmethod
    def _chip_rules(cls, v: list[str]) -> list[str]:
        return check_model_chips(v)


class DiaryTurn(CoachReply):
    """일기 대화 한 턴. 한 문장 질문 + 어르신이 버튼으로 고를 짧은 답 2개(빈칸을 빼고 6자 이내)."""

    # diary_buddy 의 모델 출력 (docstring 이 스키마 description 으로 모델에게 간다).
    # 화면에 보이는 답은 회상과 같은 상한 (D52 ④)

    @field_validator("suggestions")
    @classmethod
    def _model_chip_rules(cls, v: list[str]) -> list[str]:
        return check_model_chips(v)


class FamilyQuestion(BaseModel):
    """가족 일기 동무의 말. 가족이 쓴 말을 짧게 받아 준 뒤 묻는 질문 하나(물음표 1개로 끝남)."""

    # family_buddy 의 모델 출력 (FR-DI-006, D58). 가족 화면(FDIARY_002) 질문 카드에 그대로 보인다
    question: str = Field(min_length=1, max_length=MODEL_TEXT_MAX)

    @field_validator("question")
    @classmethod
    def _question_rules(cls, v: str) -> str:
        v = check_text(v)
        if question_marks(v) != 1 or not v.endswith(("?", "？")):
            raise ValueError("질문 하나로, 물음표(?)로 끝낸다")
        return v


class FamilyDraft(BaseModel):
    """가족 일기 초안. 가족이 쓴 말과 답만으로 쓴 존댓말 1인칭 본문(최대 4문장·200자). 어르신께 소리로 읽어 드린다."""

    # family_draft 의 모델 출력 (FR-DI-007, D58·D61). 가족이 FDIARY_003 에서 고쳐 쓴 뒤 올린다
    body: str = Field(min_length=1, max_length=FAMILY_DRAFT_MAX)

    @field_validator("body")
    @classmethod
    def _body_rules(cls, v: str) -> str:
        return check_banned(v.strip())


class WeeklyCard(BaseModel):
    """주간 이야기 카드 한 장 — weekly_summary 의 모델 출력 (FR-FD-005, D62).

    규칙 검사는 ai/weekly.check 가 카드마다 한다. 한 장이 걸려도 나머지를 살리려고 여기서는 모양만 본다.
    """

    ref: str  # 입력 pairs 의 ref — 근거가 된 어르신 답
    answer: str  # 가족에게 전하는 전달형 한 문장
    quote: str  # 그 답 원문에서 글자 그대로 옮긴 구절


class WeeklyCards(BaseModel):
    cards: list[WeeklyCard]


class DiaryDraft(BaseModel):
    """일기 초안. 어르신이 하신 말만으로 쓴 1인칭 본문(말씀만큼, 최대 5문장), 기분, 그릴 사물(최대 3개, 영어 단어)."""

    # FR-DI-003/005. docstring 은 스키마 description 으로 모델에게 가므로 모델이 읽을 말로 적는다.

    body: str = Field(min_length=1, max_length=400)
    mood: Literal["SUNNY", "CLOUDY", "RAINY", "MOON"]
    # 그림일기에 그릴 사물 최대 3개, 영어 이름 (사람·얼굴·건물·특정 장소·글자 제외). 비면 기분 그림(D69)
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


SCENE_MAX = 60  # 보이는 모습 한 줄 — 넘으면 자른다 (photos.ai_scene VARCHAR(100) 안, D71)


class PhotoLabel(BaseModel):
    """사진 한 장의 분류 (FR-ME-003, D71). 보이는 모습을 먼저 적고 그다음 이름표를 고른다(필드 순서 = 쓰는 순서)."""

    # 검사는 너그럽게: 목록 밖 값은 none, 긴 한 줄은 자름 — 다시 부르지 않는다(분류는 다시 불러도 비슷하다).
    # 인젝션 피해는 오분류로 한정된다(D14). enum 은 구조화 출력이 목록 밖 값을 못 쓰게 한다.
    scene: str
    usable: bool
    is_old: bool
    season: Literal["SPRING", "SUMMER", "AUTUMN", "WINTER", "NONE"]
    activity: str = Field(json_schema_extra={"enum": [*TAXONOMY["activity"], "none"]})
    category: str = Field(json_schema_extra={"enum": [*TAXONOMY["category"], "none"]})
    confidence: float

    @field_validator("scene")
    @classmethod
    def _scene_rules(cls, v: str) -> str:
        v = " ".join(v.split())[:SCENE_MAX]
        return "" if any(w in v for w in BANNED_WORDS) else v  # 대화 재료라 금지어가 섞이면 버린다

    @field_validator("activity", "category")
    @classmethod
    def _in_list(cls, v: str, info) -> str:
        return v if v in TAXONOMY[info.field_name] else "none"

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return 0.0 if math.isnan(v) else min(1.0, max(0.0, v))
