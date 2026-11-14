"""회상 코치 (FR-AI-001·002·003·005·006, D42) — 회상 질문 3턴 → 문제 은행 문제 1개 → 자유 회상 → 마무리.
일기 동무 (FR-DI-003, D36) — 질문 3개(뭐 하셨어요 → 누구랑 → 기분은) + 초안(본문·기분·그릴 사물).
  옛 사진이면 1·2번은 그 사진 속 그때를 묻는다 (FR-DI-002, D58).
  가족 모드 (FR-DI-006·007, D58) — 가족이 쓴 몇 마디 → 질문 1개 → 답 → 존댓말 1인칭 초안. 저장은 화면이 한다.

4번째 질문(생각 문제, D72 섞기): 유형은 코드가 돌려 정하고(ai/quiz.py), 모델이 맞장구 + 그 유형 문제를 사진·대화에
맞춰 쓴다. 코드가 유형 틀·정답 있는 질문(연도·나이·이름 맞히기)을 검사해 걸리면 문제 은행 원문으로 바꾼다.
question_type 은 모델이 아니라 여기서 정한다: 모델 질문 RECALL, 생각 문제 = 그 유형(은행 문제면 qtype), 마무리 CLOSING.
모델은 어르신 직전 말로 signal(NONE|LOW|SAD|RISK|STOP)과 private 을 함께 낸다. LOW 는 기록하고 이어 가고,
SAD·RISK·STOP 이면 그 턴 말은 마무리 인사다 (FR-AI-005, D55). 위급(RISK) 마무리는 코드 문장.
되짚기(RECHECK)·story_facts 는 AI-07(#46).
LLM 이 실패하면(키 없음·검증 실패·장애) 고정 문장으로 대화를 이어 간다 (D14). 문제 턴은 원문만 낸다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.ai import llm
from app.ai.quiz import Quiz, QuizPlan
from app.ai.schemas import (
    BANNED_WORDS,
    CoachReply,
    CoachTurn,
    DiaryDraft,
    DiaryTurn,
    FamilyDraft,
    FamilyQuestion,
    question_marks,
)
from app.config import DIARY_TURNS, FAMILY_DRAFT_MAX, MAX_TURNS, today_kst


@dataclass
class CoachContext:
    elder_name: str
    elder_honorific: str
    photo: dict[str, Any] | None = None  # {caption, people_note, taken_at}
    turns: list[dict[str, str]] = field(default_factory=list)  # [{speaker: AI|ELDER, text}]
    old_photo: bool = False  # 일기 사진이 옛 사진(분류 추정) — 일기 1·2번을 그 사진 속 그때로 (FR-DI-002, D58)
    # 분류 AI 가 본 '보이는 모습' 한 줄 (D71). 질문 재료로만 — 일기 초안(diary_draft)에는 넘기지 않는다
    scene: str | None = None


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
# 저신뢰 확인 질문에 대한 답 (D52 ③, D33 을 바꿈). 말로 해도 칩으로 눌러도 같다. 앞뒤 문장부호·띄어쓰기는 뺀 뒤 비교
CONFIRM_YES = {"맞아요", "맞아", "맞습니다", "맞네", "맞어", "네", "예", "응", "그래요", "그래"}
CONFIRM_YES |= {"네맞아요", "예맞아요", "응맞아"}
CONFIRM_NO = {"다시말할게요", "아니요", "아니", "아뇨", "아니에요", "틀렸어요", "아니야"}
SKIP_CHIP = "다음에 할게요"  # 옛 넘기기 칩 (11/12 전). 문제 칩은 답 2개만이라(D52 ⑧) 모델이 이 칩을 내도 거른다
QUIZ_FALLBACK_CHIPS = ["잘 모르겠어요"]  # 열린 문제인데 모델이 칩을 못 만들었을 때
ENDING_SIGNALS = ("SAD", "RISK", "STOP")  # 이 신호면 그 턴 말은 마무리 — 호출자가 대화를 끝낸다. LOW 는 이어 감 (D55)
# 위급 표현 뒤 마무리 (D55, 11/13 사용자: 상담 번호 안내 없이 마무리만). 모델이 지어내지 않게 코드 문장
RISK_CLOSING = CoachReply(
    text="많이 힘드셨겠어요. 이야기해 주셔서 고마워요. 오늘은 여기까지 하고 편히 쉬세요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)
WEEKDAYS = "월화수목금토일"


def _data(ctx: CoachContext, turn_no: int, closing: bool = False, max_turns: int = MAX_TURNS) -> dict[str, Any]:
    # 데이터만 넘긴다. 지시는 prompts/*.md(system) 에만 (D14).
    return {
        "elder_name": ctx.elder_name,
        "elder_honorific": ctx.elder_honorific,
        "photo": ctx.photo,
        "scene": ctx.scene,  # 분류 AI 가 본 모습 한 줄 — 틀릴 수 있어 '~같아요'로만 (D71, 프롬프트 규칙)
        "turns": ctx.turns[-12:],
        "turn_no": turn_no,
        "max_turns": max_turns,
        "closing": closing,
    }


def _memory_data(
    ctx: CoachContext, turn_no: int, closing: bool = False, quiz: QuizPlan | None = None, max_turns: int = MAX_TURNS
) -> dict[str, Any]:
    """회상 대화용 데이터. 오늘 날짜·요일은 묻지 않고 말에 섞어 알려 주기 위해 넘긴다 (FR-AI-003)."""
    d = today_kst()
    quiz_data = {"type": quiz.qtype, "example": quiz.example, "recent": quiz.recent} if quiz else None
    return _data(ctx, turn_no, closing, max_turns) | {
        "today": f"{d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일",
        "quiz": quiz_data,
    }


def _closing_reply(text: str) -> CoachReply:
    """모델이 쓴 마무리 인사. 질문이 섞이면 고정 인사로 (마무리는 질문 없이)."""
    if question_marks(text):
        return FALLBACK_CLOSING
    return CoachReply(text=text, suggestions=[], question_type="CLOSING", choice_mode="TWO_BUTTONS")


def _is_skip(text: str) -> bool:
    return text.strip().rstrip(".") == SKIP_CHIP


def _quiz_reply(quiz: Quiz, lead: str, chips: list[str]) -> CoachReply:
    """맞장구(모델) + 문제 은행 원문(코드). 칩 = 답 2개(2지선다면 선택지)만 — 넘기기는 말로 (D52 ⑧)."""
    # 넘기기 칩·겹친 칩을 먼저 거른 뒤에 비었으면 기본 칩 (화면은 2개가 안 되면 기본 칩으로 채운다)
    suggestions = list(dict.fromkeys(c for c in (quiz.choices or chips) if not _is_skip(c)))[:2] or QUIZ_FALLBACK_CHIPS
    lead = re.split(r"(?<=[.!])\s+", lead.strip())[0]  # 맞장구는 첫 문장만 (원문까지 2문장 이내, FR-AI-006)
    if lead and not question_marks(lead):  # 맞장구에 질문이 섞이면 질문이 2개가 되므로 버린다
        try:
            return CoachReply(text=f"{lead} {quiz.prompt_text}", suggestions=suggestions, question_type=quiz.qtype)
        except ValidationError:
            pass  # 합쳐서 120자 초과 등 → 원문만
    return CoachReply(text=quiz.prompt_text, suggestions=suggestions, question_type=quiz.qtype)


# 생각 문제에 쓰면 안 되는 말 — 정답이 있는 질문(연도·나이·날짜·이름 맞히기)과 시험 말투 (FR-AI-003, D72).
# 금지어(점수·정답·틀리 …)는 CoachTurn 이 따로 검사한다. 걸리면 문제 은행 원문으로 바꾼다
QUIZ_NOT = re.compile(
    r"몇\s*년도|몇\s*살|연세|오늘(은|이)?\s*(며칠|몇\s*월)|무슨\s*요일|이름이\s*(뭐|무엇)|성함|누구(예요|일까|인지)"
    r"|맞혀|맞춰|맞히|퀴즈|기억력"
)
THEN_WORDS = ("옛날", "그때", "예전", "젊으셨을", "어릴 때")
NOW_WORDS = ("요즘", "지금", "요새")
KNOWHOW_WORDS = ("어떻게", "어떤", "뭘", "무엇", "무슨", "몇", "요령", "방법")  # 방법·요령·했던 것을 묻는 말
TWO_CHOICE = re.compile(r"요,\s*\S.*요\?$")  # '업어서 재우셨어요, 안아서 재우셨어요?' — 둘 중 고르기


def quiz_ok(qtype: str, text: str) -> bool:
    """AI 가 쓴 생각 문제가 그 유형의 틀을 지켰는지 (D72). 아니면 호출자가 문제 은행 원문으로 바꾼다."""
    if QUIZ_NOT.search(text):
        return False
    marks = question_marks(text)
    if qtype == "REMEMBER":  # 떠올리기 = '…, 생각나는 대로 말씀해 주세요.' — 말한 개수만 기록 (FR-AI-003)
        return marks == 0 and ("생각나는 대로" in text or "떠오르는 대로" in text)
    if marks != 1 or not text.rstrip().endswith("?"):
        return False
    if qtype == "THEN_NOW":  # 그때와 요즘을 견준다
        return any(w in text for w in THEN_WORDS) and any(w in text for w in NOW_WORDS)
    # KNOWHOW: 해 보신 일의 방법·요령을 묻는 질문 — 그냥 회상 질문('누구랑 하셨어요?')이면 은행 문제로
    question = re.split(r"(?<=[.!])\s+", text.strip())[-1]
    return any(w in question for w in KNOWHOW_WORDS) or bool(TWO_CHOICE.search(question))


def _skipped_quiz(ctx: CoachContext, signal: str) -> bool:
    """문제에 넘기자고 답했는지 — 그 문제만 넘기고 대화는 이어 간다 (FR-AI-003, D52 ⑧).

    넘기기 칩이 없어져 '다음에 할게요·모르겠어요'를 말로 한다.
    모델이 그 말을 STOP 으로 읽어도 '그만'이 없으면 넘기기로 본다
    (진짜 그만이면 다음 질문에서 한 번 더 말하면 끝난다). 옛 칩 글자 그대로면 SAD 도 무시한다(D42 그대로).
    """
    if len(ctx.turns) < 2 or not ctx.turns[-2].get("quiz"):
        return False
    said = ctx.turns[-1]["text"]
    return _is_skip(said) or (signal == "STOP" and "그만" not in said)


def confirm_answer(text: str) -> str | None:
    """저신뢰 확인 질문('제가 ○○ 라고 들었어요…')에 대한 답이 '맞다'(YES)·'아니다'(NO)인지. 그 밖의 말은 None(새 답)."""
    t = re.sub(r"[\s.,!?~]", "", text)
    if t in CONFIRM_YES:
        return "YES"
    if t in CONFIRM_NO:
        return "NO"
    return None


def next_question(
    ctx: CoachContext, turn_no: int, quiz: QuizPlan | None = None, max_turns: int = MAX_TURNS
) -> tuple[CoachReply, str, bool]:
    """turn_no 번째 AI 말, signal(NONE|LOW|SAD|RISK|STOP), private.

    quiz(생각 문제 계획)가 있으면 맞장구 + 모델이 쓴 그 유형 문제, 검사에 걸리면 맞장구 + 문제 은행 원문 (D72).

    max_turns = 이 대화의 최대 질문 수 (오늘의 한 장 6, 사진첩 2 — routers/sessions.py 가 넘긴다).
    signal 이 SAD·RISK·STOP 이면 reply 는 마무리 인사다 — 호출자가 대화를 끝낸다 (FR-AI-005, D55). LOW 는 이어 간다.
    """
    try:
        out = llm.call_json("memory_coach", _memory_data(ctx, turn_no, quiz=quiz, max_turns=max_turns), CoachTurn)
    except (llm.LlmError, NotImplementedError):
        return (_quiz_reply(quiz.fallback, "", []) if quiz else FALLBACK_QUESTION), "NONE", False
    if out.signal != "NONE" and not any(t["speaker"] == "ELDER" for t in ctx.turns):  # 어르신 말 전의 신호 → 무시
        return FALLBACK_QUESTION, "NONE", False
    if out.signal == "RISK":  # 위급은 문제 넘기기로 보지 않는다
        return RISK_CLOSING, "RISK", out.private
    if out.signal in ENDING_SIGNALS:
        if _skipped_quiz(ctx, out.signal):  # 문제를 넘기는 말 — 대화를 끝내지 않는다 (FR-AI-003)
            return FALLBACK_QUESTION, "NONE", out.private
        return _closing_reply(out.text), out.signal, out.private
    if quiz:
        if quiz_ok(quiz.qtype, out.text):
            chips = list(dict.fromkeys(c for c in out.suggestions if not _is_skip(c)))[:2] or QUIZ_FALLBACK_CHIPS
            return CoachReply(text=out.text, suggestions=chips, question_type=quiz.qtype), out.signal, out.private
        # 틀을 안 지킴 → 맞장구(첫 문장) + 은행 원문. 모델 칩은 모델 문제에 맞춘 것이라 쓰지 않는다
        return _quiz_reply(quiz.fallback, out.text, []), out.signal, out.private
    reply = CoachReply(text=out.text, suggestions=out.suggestions[:2], question_type="RECALL")  # 늘 2개 (D52 ④)
    return reply, out.signal, out.private


def closing(ctx: CoachContext, turn_no: int, max_turns: int = MAX_TURNS) -> tuple[CoachReply, str, bool]:
    """마무리 인사와 signal·private. 마지막 답의 기운 없음·위급도 남기도록 signal 을 돌려준다 (D55)."""
    try:
        out = llm.call_json("memory_coach", _memory_data(ctx, turn_no, closing=True, max_turns=max_turns), CoachTurn)
    except (llm.LlmError, NotImplementedError):
        return FALLBACK_CLOSING, "NONE", False
    if out.signal == "RISK":
        return RISK_CLOSING, "RISK", out.private
    return _closing_reply(out.text), out.signal, out.private


def confirm_question(heard: str) -> CoachReply:
    """STT 신뢰도가 낮을 때 (D5): LLM 을 부르지 않고 확인만 묻는다.

    들은 말을 되읊되, 금지어 검사에 걸리면(예: '저하고' 의 '저하') 되읊지 않는 고정 문장으로.
    """
    heard = heard[:40].replace("?", "").replace("？", "")
    try:
        text = f"제가 '{heard}' 라고 들었어요. 맞으면 맞아요라고 해 주세요."
        return CoachReply(text=text, suggestions=CONFIRM_SUGGESTIONS, question_type="NONE", choice_mode="TWO_BUTTONS")
    except ValidationError:
        text = "제가 잘 들었는지 모르겠어요. 맞으면 맞아요라고 해 주세요."
        return CoachReply(text=text, suggestions=CONFIRM_SUGGESTIONS, question_type="NONE", choice_mode="TWO_BUTTONS")


# ---------------------------------------------------------------- 일기 동무 (FR-DI-003, D36)
DIARY_MOODS = {"맑음": "SUNNY", "구름": "CLOUDY", "비": "RAINY", "달": "MOON"}
DIARY_QUESTIONS = [  # 1·2번 질문의 고정 문장 (LLM 이 실패할 때·mock)
    CoachReply(text="오늘은 뭐 하셨어요?", suggestions=["집에 있었어요", "밖에 다녀왔어요"], question_type="NONE"),
    CoachReply(text="누구랑 계셨어요?", suggestions=["혼자요", "가족이랑요", "친구랑요"], question_type="NONE"),
]
# 옛 사진 일기의 1번 고정 문장 (FR-DI-002, D58). 분류는 추정이라 단정하지 않는다('같네요')
DIARY_OLD_PHOTO_QUESTION = CoachReply(
    text="옛날 사진 같네요. 언제 찍으신 사진이에요?", suggestions=["젊을 때요", "잘 모르겠어요"], question_type="NONE"
)
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
    """turn_no 번째 일기 질문 (1 뭐 하셨어요 → 2 누구랑 → 3 기분, FR-DI-003).

    옛 사진(ctx.old_photo)이면 1·2번은 오늘 일 대신 그 사진 속 그때를 묻는다 (FR-DI-002, D58). 3번 기분은 같다.
    """
    # ponytail: 질문 수는 3개 고정. 첫 답에 함께한 사람이 이미 나오면 2번은 프롬프트가 다른 것을 묻는다
    # (diary_buddy.md 규칙 3). 질문 수 자체를 줄이려면 diary_buddy 출력에 '건너뛰기' 칸을 더한다.
    if turn_no >= DIARY_TURNS:
        return DIARY_MOOD_QUESTION
    data = _data(ctx, turn_no, max_turns=DIARY_TURNS) | {"old_photo": ctx.old_photo}
    try:
        return llm.call_json("diary_buddy", data, DiaryTurn)
    except (llm.LlmError, NotImplementedError):
        q = DIARY_OLD_PHOTO_QUESTION if ctx.old_photo and turn_no == 1 else diary_fallback(turn_no)
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
        # LLM 이 없거나 실패: 어르신 말을 그대로 이어 붙인다(말씀에 없는 내용 없음). 사물을 모르니 기분 그림(D69).
        # 본문은 화면에 보이고 소리로 읽히므로 금지어가 든 답은 뺀다 (NFR-DE-003, confirm_question 과 같은 규칙).
        said = " ".join(
            a.rstrip(" .") + "." for a in answers if not mood_of(a) and not any(w in a for w in BANNED_WORDS)
        )
        draft = DiaryDraft.model_construct(
            body=said[:400] or "오늘 이야기를 나눴다.", mood=picked or "CLOUDY", draw_objects=[]
        )
    return draft.model_copy(update={"mood": picked}) if picked else draft


# ------------------------------------------------------------ 가족 일기 동무 (FR-DI-006·007, D58)
# 가족이 쓴 몇 마디 → 질문 1개 → 답 → 초안. 서버는 저장하지 않는다
# (가족이 FDIARY_003 에서 고쳐 POST /rooms/{id}/diaries).
FAMILY_QUESTION = "그때 어떠셨는지 조금 더 들려주시겠어요?"  # LLM 이 실패할 때·mock·하루 상한
# 쓴 말·답이 모두 금지어 검사에 걸렸을 때 (어르신 초안의 '오늘 이야기를 나눴다.'와 같은 자리)
FAMILY_DRAFT_EMPTY = "오늘 소식을 전해요."


def family_question(text: str) -> str:
    """가족이 쓴 말 → 질문 1개 (FR-DI-006). 가족 글도 지시가 아니라 데이터로만 넘긴다 (D14)."""
    try:
        return llm.call_json("family_buddy", {"text": text}, FamilyQuestion).question
    except (llm.LlmError, NotImplementedError):
        return FAMILY_QUESTION


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?", "~", "…")) else text + "."


def family_draft(text: str, question: str, answer: str) -> str:
    """쓴 말 + 질문 + 답 → 가족 존댓말 1인칭 초안 (FR-DI-007).

    쓴 말·답에 없는 내용은 넣지 않는다 (diary_draft 와 같은 규칙).
    """
    try:
        data = {"text": text, "question": question or None, "answer": answer or None}
        return llm.call_json("family_draft", data, FamilyDraft).body
    except (llm.LlmError, NotImplementedError):
        # 쓴 말과 답을 그대로 잇는다(질문은 AI 의 말이라 넣지 않는다). 어르신께 읽어 드리는 글이라
        # 금지어가 든 문장은 뺀다 — 덩어리째 빼면 한 문장 때문에 쓴 말이 다 사라진다 (11/13 실제 평가)
        sentences = [p for s in (text, answer) for p in re.split(r"(?<=[.!?~…])\s+", " ".join(s.split())) if p]
        kept = [_sentence(p) for p in sentences if not any(w in p for w in BANNED_WORDS)]
        # 200자에 들어가는 문장까지만 — 문장 중간에서 끊긴 글이 어르신께 읽히지 않게 (D61)
        said = ""
        for sentence in kept:
            if len(said) + len(sentence) + (1 if said else 0) > FAMILY_DRAFT_MAX:
                break
            said = f"{said} {sentence}".lstrip()
        # 첫 문장 하나가 200자를 넘을 때만 글자 수로 자른다
        return said or " ".join(kept)[:FAMILY_DRAFT_MAX] or FAMILY_DRAFT_EMPTY
