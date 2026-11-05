"""회상 코치 — 최소 버전 (초석 원안 D). 인사 1문장 + 회상 질문 + 마무리.

문제 은행 규칙(노하우→떠올리기→그때vs지금), 되짚기(RECHECK), story_facts 는 11/9 주 홍진성 PR 에서 채운다.
LLM 이 실패하면(키 없음·검증 실패·장애) 고정 문장으로 대화를 이어 간다 (D14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai import llm
from app.ai.schemas import CoachReply
from app.config import MAX_TURNS


@dataclass
class CoachContext:
    elder_name: str
    elder_honorific: str
    photo: dict[str, Any] | None = None  # {caption, people_note, taken_at}
    turns: list[dict[str, str]] = field(default_factory=list)  # [{speaker: AI|ELDER, text}]


FALLBACK_QUESTION = CoachReply(
    text="그 사진 보니까 어떤 생각이 드세요?",
    suggestions=["좋아요", "글쎄요", "기억 안 나요"],
    question_type="RECALL",
    choice_mode="CHIPS",
)
FALLBACK_CLOSING = CoachReply(
    text="오늘 이야기 들려주셔서 고마워요. 내일 또 만나요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)
CONFIRM_SUGGESTIONS = ["맞아요", "다시 말할게요"]


def _data(ctx: CoachContext, turn_no: int, closing: bool = False) -> dict[str, Any]:
    # 데이터만 넘긴다. 지시는 prompts/memory_coach.md(system) 에만 (D14).
    return {
        "elder_name": ctx.elder_name,
        "elder_honorific": ctx.elder_honorific,
        "photo": ctx.photo,
        "turns": ctx.turns[-12:],
        "turn_no": turn_no,
        "max_turns": MAX_TURNS,
        "closing": closing,
    }


def next_question(ctx: CoachContext, turn_no: int) -> CoachReply:
    """turn_no 번째 AI 질문 (1 = 첫 인사 + 첫 질문)."""
    try:
        return llm.call_json("memory_coach", _data(ctx, turn_no), CoachReply)
    except (llm.LlmError, NotImplementedError):
        return FALLBACK_QUESTION


def closing(ctx: CoachContext, turn_no: int) -> CoachReply:
    try:
        return llm.call_json("memory_coach", _data(ctx, turn_no, closing=True), CoachReply)
    except (llm.LlmError, NotImplementedError):
        return FALLBACK_CLOSING


def confirm_question(heard: str) -> CoachReply:
    """STT 신뢰도가 낮을 때 (D5): LLM 을 부르지 않고 확인만 묻는다."""
    heard = heard[:40]
    return CoachReply(
        text=f"제가 '{heard}' 라고 들었어요. 맞으면 맞아요를 눌러 주세요.",
        suggestions=CONFIRM_SUGGESTIONS,
        question_type="NONE",
        choice_mode="TWO_BUTTONS",
    )
