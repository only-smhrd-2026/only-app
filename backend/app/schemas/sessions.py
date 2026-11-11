"""세션 API 계약 v1 (설계안 3절). 초석에서 고정 — 모양을 바꾸면 김승희(화면)를 리뷰어로."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

SessionKind = Literal["MEMORY", "ALBUM", "DIARY"]
InputType = Literal["VOICE", "CHIP", "BUTTON"]
ChoiceMode = Literal["CHIPS", "TWO_BUTTONS"]
QuestionType = Literal["RECALL", "REMEMBER", "KNOWHOW", "THEN_NOW", "COMMON", "RECHECK", "CLOSING", "NONE"]
SessionState = Literal["CONTINUE", "ENDED"]
EndReason = Literal["COMPLETED", "USER_STOP", "NO_RESPONSE", "ERROR", "LIMIT"]


class AiOut(BaseModel):
    text: str
    audio_b64: str | None = None  # TTS mp3 base64. None 이면 브라우저 speechSynthesis (D5)
    suggestions: list[str] = Field(default_factory=list, max_length=4)  # 일기 기분 질문만 4개
    choice_mode: ChoiceMode = "CHIPS"
    question_type: QuestionType = "RECALL"


class SessionCreateIn(BaseModel):
    session_id: uuid.UUID  # 클라이언트가 생성 (재시도 멱등)
    kind: SessionKind
    photo_id: int | None = None
    pick_id: int | None = None


class SessionOut(BaseModel):
    session_id: uuid.UUID
    kind: SessionKind  # 회상 화면을 사진첩 대화에도 쓰므로 화면이 둘을 가른다
    photo_url: str | None  # /api/media/{key}. 사진 없는 대화(사진 안 고른 일기)는 None
    ai: AiOut
    state: SessionState
    end_reason: EndReason | None = None
    turn_no: int
    input_locked: bool = False


class SessionGetOut(BaseModel):
    session_id: uuid.UUID
    kind: SessionKind
    photo_url: str | None  # 새로고침 뒤에도 이 대화의 사진을 다시 보여 주게
    state: SessionState
    end_reason: EndReason | None = None
    last_ai: AiOut | None
    turn_no: int
    input_locked: bool


class TurnIn(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    input_type: InputType
    stt_confidence: float | None = Field(default=None, ge=0, le=1)
    retried: bool = False  # 확인 질문 뒤 "맞아요" 로 같은 문장을 다시 보낼 때 true
    event: Literal["NO_RESPONSE"] | None = None


class SessionEndIn(BaseModel):
    reason: EndReason


class SessionEndOut(BaseModel):
    session_id: uuid.UUID
    state: SessionState
    end_reason: EndReason | None
    turn_no: int
