"""회상 코치 — 최소 버전 (초석 원안 D). 인사 1문장 + 회상 질문 + 마무리.
일기 동무 (FR-DI-003, D36) — 질문 3개(뭐 하셨어요 → 누구랑 → 기분은) + 초안(본문·기분·그릴 사물).

문제 은행 규칙(노하우→떠올리기→그때vs지금), 되짚기(RECHECK), story_facts 는 11/9 주 홍진성 PR 에서 채운다.
LLM 이 실패하면(키 없음·검증 실패·장애) 고정 문장으로 대화를 이어 간다 (D14). mock 도 이 고정 문장을 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.ai import llm
from app.ai.schemas import BANNED_WORDS, CoachReply, DiaryDraft
from app.config import DIARY_TURNS, MAX_TURNS


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


def _data(ctx: CoachContext, turn_no: int, closing: bool = False, max_turns: int = MAX_TURNS) -> dict[str, Any]:
    # 데이터만 넘긴다. 지시는 prompts/*.md(system) 에만 (D14).
    return {
        "elder_name": ctx.elder_name,
        "elder_honorific": ctx.elder_honorific,
        "photo": ctx.photo,
        "turns": ctx.turns[-12:],
        "turn_no": turn_no,
        "max_turns": max_turns,
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
    """STT 신뢰도가 낮을 때 (D5): LLM 을 부르지 않고 확인만 묻는다.

    들은 말을 되읊되, 금지어 검사에 걸리면(예: '저하고' 의 '저하') 되읊지 않는 고정 문장으로.
    """
    heard = heard[:40].replace("?", "").replace("？", "")
    try:
        text = f"제가 '{heard}' 라고 들었어요. 맞으면 맞아요를 눌러 주세요."
        return CoachReply(text=text, suggestions=CONFIRM_SUGGESTIONS, question_type="NONE", choice_mode="TWO_BUTTONS")
    except ValidationError:
        text = "제가 잘 들었는지 모르겠어요. 맞으면 맞아요를 눌러 주세요."
        return CoachReply(text=text, suggestions=CONFIRM_SUGGESTIONS, question_type="NONE", choice_mode="TWO_BUTTONS")


# ---------------------------------------------------------------- 일기 동무 (FR-DI-003, D36)
DIARY_MOODS = {"맑음": "SUNNY", "구름": "CLOUDY", "비": "RAINY", "달": "MOON"}
DIARY_QUESTIONS = [  # 1·2번 질문의 고정 문장 (LLM 이 실패할 때·mock)
    CoachReply(text="오늘은 뭐 하셨어요?", suggestions=["집에 있었어요", "밖에 다녀왔어요"], question_type="NONE"),
    CoachReply(text="누구랑 계셨어요?", suggestions=["혼자요", "가족이랑요", "친구랑요"], question_type="NONE"),
]
# 3번(마지막)은 늘 기분 칩 4개 — 칩을 고르면 기분 날씨가 바로 정해진다.
# 모델 출력용 상한(CoachReply 칩 ≤3)을 넘는 고정 문장이라 검사 없이 만든다(금지어 없음·물음표 1개).
DIARY_MOOD_QUESTION = CoachReply.model_construct(
    text="오늘 기분은 어떠셨어요?", suggestions=list(DIARY_MOODS), question_type="NONE", choice_mode="CHIPS"
)
DIARY_STOP = CoachReply(  # 무응답으로 끝남 → 저장하지 않으므로 "일기를 써 볼게요"라고 하지 않는다
    text="오늘은 여기까지 할게요. 다음에 또 이야기해요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)
DIARY_CLOSING = CoachReply(
    text="고마워요. 들려주신 이야기로 일기를 써 볼게요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)


def diary_fallback(turn_no: int) -> CoachReply:
    """turn_no 번째 일기 질문의 고정 문장."""
    return DIARY_MOOD_QUESTION if turn_no >= DIARY_TURNS else DIARY_QUESTIONS[max(turn_no, 1) - 1]


def diary_question(ctx: CoachContext, turn_no: int) -> CoachReply:
    """turn_no 번째 일기 질문 (1 뭐 하셨어요 → 2 누구랑 → 3 기분, FR-DI-003)."""
    # ponytail: 질문 수는 3개 고정. 첫 답에 함께한 사람이 이미 나오면 2번은 프롬프트가 다른 것을 묻는다
    # (diary_buddy.md 규칙 3). 질문 수 자체를 줄이려면 diary_buddy 출력에 '건너뛰기' 칸을 더한다.
    if turn_no >= DIARY_TURNS:
        return DIARY_MOOD_QUESTION
    try:
        return llm.call_json("diary_buddy", _data(ctx, turn_no, max_turns=DIARY_TURNS), CoachReply)
    except (llm.LlmError, NotImplementedError):
        q = diary_fallback(turn_no)
        return q.model_copy(update={"text": f"{ctx.elder_honorific}, {q.text}"}) if turn_no == 1 else q


def mood_of(text: str) -> str | None:
    """기분 칩 글자 또는 말로 한 칩 이름('맑음이요', '비요.', '달이에요') → 기분 코드. 아니면 None."""
    t = re.sub(r"[\s.,!?~]", "", text)
    for tail in ("이에요", "이요", "요"):
        if t.endswith(tail) and t[: -len(tail)] in DIARY_MOODS:
            t = t[: -len(tail)]
            break
    return DIARY_MOODS.get(t)


def diary_draft(ctx: CoachContext) -> DiaryDraft:
    """일기 대화 → 초안 (1인칭 본문·기분·그릴 사물). 어르신이 기분 칩을 골랐으면 그 값이 LLM 판단보다 우선."""
    answers = [t["text"] for t in ctx.turns if t["speaker"] == "ELDER"]
    picked = next((m for m in map(mood_of, reversed(answers)) if m), None)
    data = {"elder_honorific": ctx.elder_honorific, "photo": ctx.photo, "turns": ctx.turns}
    try:
        draft = llm.call_json("diary_draft", data, DiaryDraft)
    except (llm.LlmError, NotImplementedError):
        # LLM 이 없거나 실패: 어르신 말을 그대로 이어 붙인다(말씀에 없는 내용 없음). 그릴 사물을 모르니 그림도 없다.
        # 본문은 화면에 보이고 소리로 읽히므로 금지어가 든 답은 뺀다 (NFR-DE-003, confirm_question 과 같은 규칙).
        said = " ".join(
            a.rstrip(" .") + "." for a in answers if not mood_of(a) and not any(w in a for w in BANNED_WORDS)
        )
        draft = DiaryDraft.model_construct(
            body=said[:400] or "오늘 이야기를 나눴다.", mood=picked or "CLOUDY", draw_objects=[]
        )
    return draft.model_copy(update={"mood": picked}) if picked else draft
