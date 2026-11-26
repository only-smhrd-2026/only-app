"""LLM 출력 스키마 + 코드 검사 (D14). 모델이 뭐라고 답하든 여기서 걸러야 화면에 나간다.

금지어는 data/banned_words.json (점수·정답·틀리·치매·저하 …). 모든 어르신 턴에 적용 (NFR-DE-003).
"""

from __future__ import annotations

import json
import math
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import FAMILY_DRAFT_MAX, REPLY_MAX, ROOT

BANNED_WORDS: list[str] = json.loads((ROOT / "data" / "banned_words.json").read_text("utf-8"))["words"]
# 위급 표현 조각 (D55 ① 안전망). 띄어쓰기를 뺀 어르신 말에 들어 있으면 AI 판단과 상관없이 위급으로 본다
RISK_WORDS: list[str] = json.loads((ROOT / "data" / "risk_words.json").read_text("utf-8"))["words"]
# 사진 분류 이름표 (활동 29·주제 26 + 고르는 기준 _rules, v2 D76). 정답표·문제 은행과 같은 글자 (D71)
TAXONOMY: dict = json.loads((ROOT / "data" / "taxonomy.json").read_text("utf-8"))


def has_risk_words(text: str) -> bool:
    t = re.sub(r"\W", "", text)  # 띄어쓰기와 문장부호 — 음성 인식이 "죽고, 싶어"처럼 쉼표·말줄임표를 넣는다 (11/19)
    return any(w in t for w in RISK_WORDS)


# 몸 위급 표현 조각 (11/19 응급 안전망). 띄어쓰기를 뺀 어르신 말에 들어 있으면 AI 판단과 상관없이 몸 위급으로 본다
BODY_WORDS: list[str] = json.loads((ROOT / "data" / "body_words.json").read_text("utf-8"))["words"]


def has_body_words(text: str) -> bool:
    t = re.sub(r"\W", "", text)  # has_risk_words 와 같게 — 띄어쓰기와 문장부호를 뺀 뒤 견준다
    return any(w in t for w in BODY_WORDS)


# 거친 말·성적인 말 조각 (D112 안전망). 띄어쓰기를 빼지 않고 견준다 — '씨 발라'·'개 새끼 낳았어'가 걸리지 않게
RUDE_WORDS: list[str] = json.loads((ROOT / "data" / "rude_words.json").read_text("utf-8"))["words"]


def has_rude_words(text: str) -> bool:
    return any(w in text for w in RUDE_WORDS)


# 자판 줄임말만으로 된 답 (11/26 실측: 'ㅋㅋㅋ'·'ㅇㅇ'를 뜻 모를 말로 버림, D112)
# — 모델에는 말로 바꿔 넘긴다. 저장은 원문
_JAMO_ONLY = re.compile(r"[ㅋㅎㅇㄴㅠㅜ\s.!?~]+")
_JAMO_WORDS = ((r"[ㅋㅎ]{2,}", "하하"), (r"ㅇㅇ+", "응"), (r"ㄴㄴ+", "아니"), (r"[ㅠㅜ]{2,}", "흑흑"))


def plain_jamo(text: str) -> str:
    if not _JAMO_ONLY.fullmatch(text):  # 글 속에 섞인 것·막 친 글자(ㅁㄴㅇㄹ)는 그대로 — 모델이 본다
        return text
    for pattern, word in _JAMO_WORDS:
        text = re.sub(pattern, word, text)
    return text


def check_banned(text: str) -> str:
    # 거친 말도 AI 답·칩에 넣지 않는다 — 어르신 말을 되받다가(되짚기 규칙) 그 말을 따라 하지 않게 (D112)
    hit = [w for w in (*BANNED_WORDS, *RUDE_WORDS) if w in text]
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
    """긴 추천 답은 빼고 남긴다 — 질문까지 버리지 않게 (11/24: haiku-4.5 가 '점심을 먹었어요' 7자로 두 번 다 탈락).
    모자란 칸은 화면이 기본 답으로 채운다(VoiceSession chipsFor)."""
    return [s for s in check_chips(v) if len(s.replace(" ", "")) <= MODEL_CHIP_MAX]


def _urgent_text(data):
    """위급 신호(RISK·BODY)면 모델이 쓴 말을 버린다 — 마무리는 코드 문장이라 쓰이지 않는다.

    위급한 말에는 모델이 길게 답해 글자 수 검사에 걸리고, 그러면 한 번 더 부르느라 가장 급한 순간에 몇 초가 늦는다
    (11/19 실호출 평가: 위급 5번 중 2번이 다시 부름).
    """
    if isinstance(data, dict) and data.get("signal") in ("RISK", "BODY"):
        return {**data, "text": "네.", "suggestions": []}
    return data


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


CHAT_TEXT_MAX = 120  # 잡담 한 마디 상한 — 물으신 것에 답할 때 세 문장(프롬프트는 110자를 달라고 함, D106)
CHAT_TOPIC_MAX = 20  # '지난 이야기' 제목 (프롬프트는 빈칸 빼고 15자)


class ChatTurn(BaseModel):
    """심심이 잡담 한 마디 (D106). text: 할 말, face: 심심이 표정, go: 어르신이 가자고 하신 화면, topic: 이야기 제목,
    signal: 어르신 직전 말로 본 상태, private: 가족에게 전하지 말라고 하셨는지."""

    text: str = Field(min_length=1, max_length=CHAT_TEXT_MAX)
    face: Literal["hello", "joy", "smile", "curious", "ask", "thumbs"] = "smile"
    go: Literal["NONE", "DIARY", "ALBUM", "NEWS", "MIND"] = "NONE"
    topic: str = Field(default="", max_length=CHAT_TOPIC_MAX)
    # RUDE 거친 말·UNCLEAR 뜻 모를 말 — 회상 CoachTurn 과 같음 (D112)
    signal: Literal["NONE", "LOW", "RISK", "BODY", "STOP", "RUDE", "UNCLEAR"] = "NONE"
    private: bool = False

    @model_validator(mode="before")
    @classmethod
    def _urgent(cls, data):
        return _urgent_text(data)

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str) -> str:
        v = v.strip()
        # 물음표 2개까지: "김치 열 포기요?"처럼 되받는 감탄 + 질문 하나 (11/25 시험판에서 1개 상한에 자주 걸림)
        if question_marks(v) > 2:
            raise ValueError("질문은 한 번에 하나만 (되받는 감탄 포함 물음표 ≤ 2)")
        return check_banned(v)

    @field_validator("topic")
    @classmethod
    def _topic_rules(cls, v: str) -> str:
        return " ".join(v.split())


class CoachTurn(BaseModel):
    """회상 대화 한 턴. text: 이번에 할 말, suggestions: 어르신이 고를 짧은 답, signal: 어르신 직전 말로 본 상태,
    private: 어르신이 이 이야기를 가족에게 전하지 말라고 하셨는지."""

    # memory_coach 의 모델 출력. question_type·choice_mode 는 모델이 아니라 코드가 정한다(D42) — 지어낸 질문에
    # 문제 이름표(KNOWHOW 등)가 붙어 출제 기록이 섞이거나, API 계약에 없는 값으로 500 이 나지 않게.
    text: str = Field(min_length=1, max_length=MODEL_TEXT_MAX)
    suggestions: list[str] = Field(default_factory=list, max_length=3)
    # LOW 는 기록하고 이어 감, SAD·RISK·STOP·BODY 이면 대화를 끝낸다 (FR-AI-005, D55).
    # DENY = 어제 이야기 질문에 '그런 말 안 했어' — 그 기억을 끄고 대화는 이어 간다 (FR-AI-008, D77)
    # BODY = 지금 몸이 위급하다는 말 — 가족에게 바로 알리고 화면이 119 버튼을 띄운다 (11/19 응급)
    # RUDE = 거친 말·성적인 말 — 선을 긋고 이어 감, 그 말은 일기·가족 이야기에 쓰지 않음.
    # UNCLEAR = 뜻을 알 수 없는 말(자판을 막 친 글자) — 답으로 받지 않고 같은 질문을 다시 (D112, 11/26 피드백)
    signal: Literal["NONE", "LOW", "SAD", "RISK", "STOP", "DENY", "BODY", "RUDE", "UNCLEAR"] = "NONE"
    private: bool = False  # '애들한테 말하지 마' → 그 대화는 기운 없는 날에서 뺀다. 위급만 예외 (D55 ③)

    @model_validator(mode="before")
    @classmethod
    def _urgent(cls, data):
        return _urgent_text(data)

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str) -> str:
        return check_text(v)

    @field_validator("suggestions")
    @classmethod
    def _chip_rules(cls, v: list[str]) -> list[str]:
        return check_model_chips(v)


class DiaryTurn(CoachReply):
    """일기 대화 한 턴. 한 문장 질문 + 어르신이 버튼으로 고를 짧은 답 2개(빈칸을 빼고 6자 이내)
    + 어르신 직전 답으로 본 상태(signal)."""

    # diary_buddy 의 모델 출력 (docstring 이 스키마 description 으로 모델에게 간다).
    # 화면에 보이는 답은 회상과 같은 상한 (D52 ④)
    # 어르신 직전 답에서 본 상태 (11/19 S3): LOW 기운 없는 말(기록하고 이어 감), RISK 목숨을 해치는 이야기,
    # BODY 지금 몸이 위급하다는 말 — RISK·BODY 는 코드 문장으로 마무리하고 일기로 남기지 않는다
    # RUDE 거친 말·UNCLEAR 뜻 모를 말 — 회상 CoachTurn 과 같음 (D112). STOP 그만하자는 말 — 일기로 남기지 않고 끝 (D113)
    signal: Literal["NONE", "LOW", "RISK", "BODY", "STOP", "RUDE", "UNCLEAR"] = "NONE"

    @model_validator(mode="before")
    @classmethod
    def _urgent(cls, data):
        return _urgent_text(data)

    @field_validator("suggestions")
    @classmethod
    def _model_chip_rules(cls, v: list[str]) -> list[str]:
        return check_model_chips(v)


class ComfortTurn(CoachReply):
    """힘든 말씀 뒤 위로 한 마디 + 어르신 직전 말로 본 몸 위급 여부 (D113).

    위로 중에 '방금 약 먹었어'·'가슴이 조여'처럼 지금 몸이 위급한 말이 나오면 BODY — 코드가 119 버튼과 함께 끝낸다."""

    signal: Literal["NONE", "BODY"] = "NONE"

    @model_validator(mode="before")
    @classmethod
    def _urgent(cls, data):
        return _urgent_text(data)


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


class ElderReply(BaseModel):
    """어르신이 가족 일기에 말로 하신 답을 어르신 말투 한 줄로 (40자까지). 가족에게 그대로 간다."""

    # elder_reply 의 모델 출력 (11/23 어르신 [말로 답하기]). 어르신이 확인한 뒤 POST /elder/diaries/{id}/reply
    text: str = Field(min_length=1, max_length=REPLY_MAX)

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str) -> str:
        return check_banned(" ".join(v.split()))


class WeeklyCard(BaseModel):
    """주간 이야기 카드 한 장 — weekly_summary 의 모델 출력 (FR-FD-005, D62).

    규칙 검사는 ai/weekly.check 가 카드마다 한다. 한 장이 걸려도 나머지를 살리려고 여기서는 모양만 본다.
    """

    ref: str  # 입력 pairs 의 ref — 근거가 된 어르신 답
    answer: str  # 가족에게 전하는 전달형 한 문장
    quote: str  # 그 답 원문에서 글자 그대로 옮긴 구절


class WeeklyCards(BaseModel):
    cards: list[WeeklyCard]


class StoryFactItem(BaseModel):
    """다음 대화에서 안부로 이어 물을 이야기 하나 — story_facts 의 모델 출력 (FR-AI-007, D77).

    규칙 검사는 ai/story.check 가 하나씩 한다. 하나가 걸려도 나머지를 살리려고 여기서는 모양만 본다.
    """

    ref: str  # 입력 pairs 의 ref — 근거가 된 어르신 답
    # PLAN 앞으로 하실 일·약속, EVENT 요즘 하신 일, CORRECTION 사진 내용을 바로잡아 주신 답 (FR-ME-009)
    kind: Literal["PLAN", "EVENT", "CORRECTION"]
    fact: str  # 그 답을 전하는 한 문장
    quote: str  # 그 답 원문에서 글자 그대로 옮긴 구절


class StoryFactItems(BaseModel):
    facts: list[StoryFactItem]


class DiaryDraft(BaseModel):
    """일기 초안. 어르신이 하신 말만으로 쓴 1인칭 본문(말씀만큼, 최대 5문장), 기분, 그릴 사물(최대 3개, 영어 단어)."""

    # FR-DI-003/005. docstring 은 스키마 description 으로 모델에게 가므로 모델이 읽을 말로 적는다.

    body: str = Field(min_length=1, max_length=400)
    mood: Literal["GOOD", "SO_SO", "UPSET", "LONELY"]
    # 그림일기에 그릴 사물 최대 3개, 영어 이름 (사람·얼굴·건물·특정 장소·글자 제외). 비면 그리지 않는다(D75)
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
