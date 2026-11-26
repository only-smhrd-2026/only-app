"""회상 코치 (FR-AI-001·002·003·005·006, D42) — 회상 질문 3턴 → 문제 은행 문제 1개 → 자유 회상 → 마무리.
일기 동무 (FR-DI-003, D36·D97) — 질문 5개(뭐 하셨어요 → 아직 안 나온 것 3번 → 기분은) + 초안(본문·기분·그릴 사물).
  옛 사진이면 1~4번은 그 사진 속 그때를 묻는다 (FR-DI-002, D58).
  가족 모드 (FR-DI-006·007, D58) — 가족이 쓴 몇 마디 → 질문 1개 → 답 → 존댓말 1인칭 초안. 저장은 화면이 한다.

4번째 질문(생각 문제, D72 섞기): 유형은 코드가 돌려 정하고(ai/quiz.py), 모델이 맞장구 + 그 유형 문제를 사진·대화에
맞춰 쓴다. 코드가 유형 틀·정답 있는 질문(연도·나이·이름 맞히기)을 검사해 걸리면 문제 은행 원문으로 바꾼다.
question_type 은 모델이 아니라 여기서 정한다: 모델 질문 RECALL, 생각 문제 = 그 유형(은행 문제면 qtype), 마무리 CLOSING.
모델은 어르신 직전 말로 signal(NONE|LOW|SAD|RISK|BODY|STOP)과 private 을 함께 낸다. LOW 는 기록하고 이어 가고,
SAD·RISK·BODY·STOP 이면 그 턴 말은 마무리 인사다 (FR-AI-005, D55). 위급(RISK 마음·BODY 몸) 마무리는 코드 문장.
RUDE(거친 말·성적인 말)는 모델이 선을 긋고 이어 가고,
UNCLEAR(뜻 모를 말)는 호출자가 그 말을 버리고 같은 질문을 다시 한다 (D112).
이야기 기억 (AI-07 #46, D77) — 그날 첫 회상 대화는 지난 대화의 이야기 하나로 시작한다(story_question). 그 답에
'그런 말 안 했어'면 모델이 signal DENY 를 내고 호출자가 그 기억을 끈다. 되짚기 문제(RECHECK)는 하지 않는다 — 질문마다
어르신 말을 되받아 말하는 것으로 갈음한다 (11/12 멘토 '테스트 느낌', D52·D77).
LLM 이 실패하면(키 없음·검증 실패·장애) 고정 문장으로 대화를 이어 간다 (D14). 문제 턴은 원문만 낸다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from app.ai import llm
from app.ai.quiz import Quiz, QuizPlan
from app.ai.schemas import (
    BANNED_WORDS,
    ChatTurn,
    CoachReply,
    CoachTurn,
    DiaryDraft,
    DiaryTurn,
    ElderReply,
    FamilyDraft,
    FamilyQuestion,
    question_marks,
)
from app.config import COMFORT_TURNS, DIARY_TURNS, FAMILY_DRAFT_MAX, MAX_TURNS, REPLY_MAX, today_kst


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
# AI 가 실패한 턴의 고정 질문 — 차례대로 돌려 같은 문장을 되풀이하지 않는다
# (11/24 실사용: Claude 크레딧이 끊긴 동안 사진첩 회상 1·2번 질문이 둘 다 FALLBACK_QUESTION 이었다)
FALLBACK_QUESTIONS = (
    FALLBACK_QUESTION,
    CoachReply(
        text="그날 이야기를 조금 더 들려주시겠어요?",
        suggestions=["좋아요", "다음에요"],
        question_type="RECALL",
        choice_mode="CHIPS",
    ),
    CoachReply(
        text="이 사진에서 가장 마음에 드는 건 뭐예요?",
        suggestions=["다 좋아요", "글쎄요"],
        question_type="RECALL",
        choice_mode="CHIPS",
    ),
)


def memory_fallback(turn_no: int) -> CoachReply:
    """turn_no 번째 회상 질문을 AI 가 못 만들었을 때의 고정 질문 (1번 → FALLBACK_QUESTION, 그다음은 차례로)."""
    return FALLBACK_QUESTIONS[(max(turn_no, 1) - 1) % len(FALLBACK_QUESTIONS)]


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
ENDING_SIGNALS = (
    "SAD",
    "RISK",
    "STOP",
    "BODY",
)  # 이 신호면 그 턴 말은 마무리 — 호출자가 대화를 끝낸다. LOW 는 이어 감 (D55)
# 위급 표현(마음) 뒤 (D94 바꿈, 11/23 사용자): 대화를 끝내지 않고 심심이가 위로를 잇는다 — routers/sessions._comfort.
# 어르신께 '가족에게 알렸어요'라고 말하지 않고 전화도 권하지 않는다(가족 급한 알림은 그대로 간다). 상담 번호 없음(D82).
# RISK_CLOSING 은 모델이 RISK 를 냈다는 표시로만 남는다 — 어르신께 읽히는 말은 아래 위로 문장이다
RISK_CLOSING = CoachReply(
    text="많이 힘드셨겠어요. 이야기해 주셔서 고마워요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)
# 위로 턴의 고정 문장 — AI 가 실패하거나 키가 없을 때 n 번째 위로 (질문을 강요하지 않는다)
COMFORT_LINES = (
    "많이 힘드셨겠어요. 이야기해 주셔서 고마워요. 제가 옆에서 들을게요.",
    "그런 마음이 드실 만큼 힘드셨군요. 천천히 말씀하셔도 괜찮아요.",
    "말씀해 주셔서 고마워요. 혼자 견디지 않으셔도 돼요.",
)
COMFORT_CLOSING = CoachReply(
    text="오늘 마음을 들려주셔서 고마워요. 저는 늘 여기 있을게요. 또 이야기해요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)
# 몸이 위급하다는 말 뒤 마무리 (11/19 응급). 가족 알림은 routers/sessions.py 가 같이 보내고,
# 화면이 [119 전화하기]를 띄운다.
# 숫자 119 는 소리로 '백십구'로 읽힐 수 있어 말에는 넣지 않는다 (버튼 글자에만)
BODY_CLOSING = CoachReply(
    text="몸이 많이 불편하시군요. 급하시면 아래 빨간 버튼으로 구급차를 부르세요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)
URGENT_CLOSINGS = {"RISK": RISK_CLOSING, "BODY": BODY_CLOSING}  # 위급 마무리는 모델이 지어내지 않게 코드 문장
# AI 가 답을 못 만든 턴의 signal — 어르신 말을 읽지 못했다는 뜻이라 '읽었고 신호 없음(NONE)'과 다르다.
# 호출자(routers/sessions._ask)는 NONE 처럼 이어 가되, 돌봄 일지에 '괜찮다고 하셨어요'로 적지 않는다 (11/19)
UNREAD = "UNREAD"
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
    """turn_no 번째 AI 말, signal(NONE|LOW|SAD|RISK|STOP), private. AI 가 실패하면 고정 질문과 UNREAD.

    quiz(생각 문제 계획)가 있으면 맞장구 + 모델이 쓴 그 유형 문제, 검사에 걸리면 맞장구 + 문제 은행 원문 (D72).

    max_turns = 이 대화의 최대 질문 수 (오늘의 한 장 6, 사진첩 2 — routers/sessions.py 가 넘긴다).
    signal 이 SAD·RISK·STOP 이면 reply 는 마무리 인사다 — 호출자가 대화를 끝낸다 (FR-AI-005, D55). LOW 는 이어 간다.
    """
    try:
        out = llm.call_json("memory_coach", _memory_data(ctx, turn_no, quiz=quiz, max_turns=max_turns), CoachTurn)
    except (llm.LlmError, NotImplementedError):
        return (_quiz_reply(quiz.fallback, "", []) if quiz else memory_fallback(turn_no)), UNREAD, False
    if out.signal != "NONE" and not any(t["speaker"] == "ELDER" for t in ctx.turns):  # 어르신 말 전의 신호 → 무시
        return FALLBACK_QUESTION, "NONE", False
    if out.signal in URGENT_CLOSINGS:  # 위급(마음·몸)은 문제 넘기기로 보지 않는다
        return URGENT_CLOSINGS[out.signal], out.signal, out.private
    if out.signal in ENDING_SIGNALS:
        if _skipped_quiz(ctx, out.signal):  # 문제를 넘기는 말 — 대화를 끝내지 않는다 (FR-AI-003)
            return memory_fallback(turn_no), "NONE", out.private
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
        return FALLBACK_CLOSING, UNREAD, False
    if out.signal in URGENT_CLOSINGS:
        return URGENT_CLOSINGS[out.signal], out.signal, out.private
    return _closing_reply(out.text), out.signal, out.private


def _day(d: date) -> str:
    return f"{d.month}월 {d.day}일 {WEEKDAYS[d.weekday()]}요일"


def story_question(ctx: CoachContext, fact: str, when: str, heard_on: date) -> CoachReply | None:
    """그날 첫 회상 대화의 첫 질문 — 지난 대화에서 들은 이야기를 '~하셨죠'로 꺼내 그 뒤 소식을 묻는다 (FR-AI-008, D77).

    fact = 그 이야기를 전하는 한 문장, when = '어제'·'그저께'·'며칠 전', heard_on = 들은 날 — fact 안의 '내일·모레'는
    그날 기준이라 오늘과 견줘 지난 일인지 앞일인지 모델이 가린다. AI 가 실패하거나 질문 하나로 끝나지 않으면
    None — 호출자가 고정 사진 질문으로 시작한다(그 기억은 묻지 않은 채 남는다).
    """
    data = {
        "elder_name": ctx.elder_name,
        "elder_honorific": ctx.elder_honorific,
        "today": _day(today_kst()),
        "when": when,
        "heard_on": _day(heard_on),
        "fact": fact,
    }
    try:
        out = llm.call_json("story_question", data, CoachTurn)
    except (llm.LlmError, NotImplementedError):
        return None
    if question_marks(out.text) != 1 or not out.text.endswith(("?", "？")):
        return None
    return CoachReply(text=out.text, suggestions=out.suggestions[:2], question_type="RECALL")


UNCLEAR_LEAD = "제가 잘 못 알아들었어요."
RUDE_LEAD = "그런 말씀은 들으면 제가 조금 속상해요."  # 거친 말 뒤 고정 한 마디 — 모델 말을 못 쓰는 차례에만 (D112)
RUDE_EMPATHY = ("속상", "답답", "화나", "언짢", "서운")  # 일기 모델이 거친 말 앞에 쓴 말이 이걸 담으면 그대로 둔다


def unclear(last: CoachReply, buttons: bool = False) -> CoachReply:
    """뜻을 알 수 없는 말(signal UNCLEAR, D112) 뒤 — 바로 앞 질문을 '잘 못 알아들었어요'와 함께 다시 (칩도 그대로).

    buttons(연달아 UNCLEAR_BUTTONS 번째)면 답 버튼 2개로 — 무응답 2단계와 같은 모양. 일기 기분 질문은 칩 4개 그대로.
    잡담은 앞 말이 질문이 아닐 때가 많고 답 버튼이 없어 고정 문장으로 다시 청한다."""
    if isinstance(last, ChatReply):
        return CHAT_UNCLEAR
    update = {"text": f"{UNCLEAR_LEAD} {last.text}"}
    if buttons and last.suggestions != DIARY_MOOD_QUESTION.suggestions:
        update |= {"choice_mode": "TWO_BUTTONS", "suggestions": (last.suggestions or ["네", "아니요"])[:2]}
    return last.model_copy(update=update)


# 한 대화에서 거친 말이 RUDE_END 번째면 (D112) — 꾸짖지 않고 마음을 알아 드리며 그 대화를 마무리
RUDE_CLOSING = CoachReply(
    text="오늘은 마음이 많이 불편하신가 봐요. 오늘은 여기까지 하고 푹 쉬세요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)


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
DIARY_MOODS = {"좋았어요": "GOOD", "그저 그랬어요": "SO_SO", "속상했어요": "UPSET", "쓸쓸했어요": "LONELY"}  # D75
DIARY_QUESTIONS = [  # 1~4번 질문의 고정 문장 (LLM 이 실패할 때·mock)
    CoachReply(text="오늘은 뭐 하셨어요?", suggestions=["집에 있었어요", "밖에 다녀왔어요"], question_type="NONE"),
    CoachReply(text="누구랑 계셨어요?", suggestions=["혼자요", "가족이랑요", "친구랑요"], question_type="NONE"),
    CoachReply(text="어디서 하셨어요?", suggestions=["집에서요", "밖에서요"], question_type="NONE"),
    CoachReply(text="그다음에는 뭐 하셨어요?", suggestions=["쉬었어요", "밥 먹었어요"], question_type="NONE"),
]
DIARY_MORE_QUESTIONS = [  # 더 얘기하실 때(11/25)의 고정 문장
    CoachReply(
        text="네, 더 들려주세요. 또 어떤 일이 있었어요?", suggestions=["장 봤어요", "쉬었어요"], question_type="NONE"
    ),
    CoachReply(
        text="그러셨군요. 또 생각나는 일 있으세요?", suggestions=["있어요", "그게 다예요"], question_type="NONE"
    ),
    CoachReply(text="그다음에는요?", suggestions=["쉬었어요", "그게 다예요"], question_type="NONE"),
]
# 옛 사진 일기의 1번 고정 문장 (FR-DI-002, D58). 분류는 추정이라 단정하지 않는다('같네요')
DIARY_OLD_PHOTO_QUESTION = CoachReply(
    text="옛날 사진 같네요. 언제 찍으신 사진이에요?", suggestions=["젊을 때요", "잘 모르겠어요"], question_type="NONE"
)
# 5번(마지막)은 늘 기분 칩 4개 — 칩을 고르면 일기의 기분이 바로 정해진다 (D75, 날씨에 빗대지 않는다).
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
DIARY_CLOSING = CoachReply(  # AI 가 쓴 마무리(diary_closing)가 없을 때
    text="오늘 이야기 잘 들었어요. 예쁜 일기로 써서 가족들한테도 보여 드릴게요.",
    suggestions=[],
    question_type="CLOSING",
    choice_mode="TWO_BUTTONS",
)


def diary_fallback(turn_no: int, max_turns: int = DIARY_TURNS) -> CoachReply:
    """turn_no 번째 일기 질문의 고정 문장. 마지막(max_turns)은 기분 — '더 얘기할래'로 늘면 그만큼 뒤로 (11/25)."""
    if turn_no >= max_turns:
        return DIARY_MOOD_QUESTION
    if turn_no > len(DIARY_QUESTIONS):  # '더 얘기할래'로 늘어난 질문 — 같은 질문을 되풀이하지 않게
        return DIARY_MORE_QUESTIONS[(turn_no - len(DIARY_QUESTIONS) - 1) % len(DIARY_MORE_QUESTIONS)]
    return DIARY_QUESTIONS[max(turn_no, 1) - 1]


def diary_question(ctx: CoachContext, turn_no: int, max_turns: int = DIARY_TURNS) -> CoachReply:
    """turn_no 번째 일기 질문 (1 뭐 하셨어요 → 2~4 아직 안 나온 것 → 5 기분, FR-DI-003, D97).

    옛 사진(ctx.old_photo)이면 1~4번은 오늘 일 대신 그 사진 속 그때를 묻는다 (FR-DI-002, D58). 5번 기분은 같다.
    어르신이 '더 얘기할래'라고 하시면 max_turns 가 늘고(MORE_TURNS) 그 사이는 2~4번처럼 묻는다. 기분은 늘 마지막.
    """
    # ponytail: 질문 수는 5개 고정(더 얘기하시면 +3). 2~4번은 이미 나온 것을 다시 묻지 않고
    # 아직 안 나온 사실 하나씩을 묻는다(diary_buddy.md 규칙 3).
    # 질문 수 자체를 줄이려면 diary_buddy 출력에 '건너뛰기' 칸을 더한다.
    data = _data(ctx, turn_no, max_turns=max_turns) | {"old_photo": ctx.old_photo}
    if turn_no >= max_turns:
        if not any(t["speaker"] == "ELDER" for t in ctx.turns):
            return DIARY_MOOD_QUESTION
        # 기분 질문은 고정 문장이지만 앞 답(4번째)도 AI 가 읽는다 — 뜻 모를 말·거친 말·기운 없는 말을 놓치지 않게.
        # 모델이 쓴 말은 버리고 신호만 싣는다. AI 가 실패하면 신호 없이 기분 질문
        try:
            out = llm.call_json("diary_buddy", data, DiaryTurn)
        except (llm.LlmError, NotImplementedError):
            return DIARY_MOOD_QUESTION
        mood, signal = DIARY_MOOD_QUESTION.model_dump(), getattr(out, "signal", "NONE")
        if signal == "RUDE":  # 모델이 쓴 선 긋는 말은 기분 질문 앞에 못 붙이니 고정 한 마디
            mood["text"] = f"{RUDE_LEAD} {mood['text']}"
        return DiaryTurn.model_construct(**mood, signal=signal)
    try:
        out = llm.call_json("diary_buddy", data, DiaryTurn)
    except (llm.LlmError, NotImplementedError):
        q = DIARY_OLD_PHOTO_QUESTION if ctx.old_photo and turn_no == 1 else diary_fallback(turn_no, max_turns)
        return q.model_copy(update={"text": f"{ctx.elder_honorific}, {q.text}"}) if turn_no == 1 else q
    first = re.split(r"(?<=[.!,])\s+", out.text.strip())[0]
    if getattr(out, "signal", "NONE") == "RUDE" and ("죄송" in first or not any(w in first for w in RUDE_EMPATHY)):
        # 11/26 실측: 일기 모델은 거친 말에 사과('죄송해요')하거나 못 들은 척 넘어간다 — 질문만 두고 앞말은 고정 (D112).
        # 마음을 알아 드리는 앞말('많이 답답하셨나 봐요')은 그대로 둔다 — 짜증을 거친 말로 잘못 봤을 때 덜 딱딱하게
        question = re.split(r"(?<=[.!])\s+", out.text.strip())[-1]
        out = DiaryTurn.model_construct(**(out.model_dump() | {"text": f"{RUDE_LEAD} {question}"}))
    return out


def diary_closing(ctx: CoachContext) -> CoachReply:
    """일기 대화를 다 마쳤을 때 인사 (11/25 사용자 '마무리를 잘'): 오늘 들은 일을 짚고 → 일기로 써서 보여 드린다.
    AI 가 실패하거나 질문이 섞이면 고정 문장."""
    data = _data(ctx, len(ctx.turns), closing=True, max_turns=len(ctx.turns)) | {"old_photo": ctx.old_photo}
    try:
        out = llm.call_json("diary_buddy", data, DiaryTurn)
    except (llm.LlmError, NotImplementedError):
        return DIARY_CLOSING
    # 마지막 답(기분)이 뜻 모를 말·거친 말이면 신호를 싣는다 — 호출자가 다시 묻거나 그 말을 일기에서 뺀다 (D112).
    # 그 밖의 신호는 지금처럼 보지 않는다 (위급은 낱말 안전망이 먼저 잡는다)
    signal = getattr(out, "signal", "NONE")
    signal = signal if signal in ("RUDE", "UNCLEAR") else "NONE"
    text = DIARY_CLOSING.text if question_marks(out.text) else out.text
    return DiaryTurn.model_construct(
        text=text, suggestions=[], question_type="CLOSING", choice_mode="TWO_BUTTONS", signal=signal
    )


# 마지막 답에 '더 얘기할래'가 들었는지 (11/25 실사용: 더 하고 싶다고 하셨는데 끊었다). 말이라 띄어쓰기는 안 본다
_WANTS_MORE = re.compile(
    r"더(이야기|얘기|애기|말씀|말하|할래|하고싶)|(이야기|얘기|애기|말)(을|를)?(좀|조금)?더"
    r"|할말이?(더|아직|남았|많|있)|아직(할말|안끝|이야기|얘기)|(끊|끝내)지마"
)


def wants_more(text: str) -> bool:
    return bool(_WANTS_MORE.search(re.sub(r"\s", "", text)))


def mood_of(text: str) -> str | None:
    """기분 칩 글자 또는 말로 한 칩 말('좋았어요', '그저 그랬어.', '쓸쓸했어') → 기분 코드. 아니면 None.

    띄어쓰기·문장부호·끝의 '요'는 보지 않는다. 칩 말 그대로일 때만 —
    '안 좋았어요'·'좋았어요 영자랑' 은 None(초안 AI 가 정한다).
    """
    return _MOOD_WORDS.get(_mood_key(text))


def _mood_key(text: str) -> str:
    return re.sub(r"[\s.,!?~]", "", text).removesuffix("요")


_MOOD_WORDS = {_mood_key(label): code for label, code in DIARY_MOODS.items()}


def diary_draft(ctx: CoachContext) -> DiaryDraft:
    """일기 대화 → 초안 (1인칭 본문·기분·그릴 사물). 어르신이 기분 칩을 골랐으면 그 값이 LLM 판단보다 우선.

    거친 말로 적힌 어르신 답(rude, D112)은 일기 재료에서 뺀다."""
    turns = [t for t in ctx.turns if not t.get("rude")]
    answers = [t["text"] for t in turns if t["speaker"] == "ELDER"]
    picked = next((m for m in map(mood_of, reversed(answers)) if m), None)
    data = {"elder_honorific": ctx.elder_honorific, "photo": ctx.photo, "turns": turns}
    try:
        draft = llm.call_json("diary_draft", data, DiaryDraft)
    except (llm.LlmError, NotImplementedError):
        # LLM 이 없거나 실패: 어르신 말을 그대로 이어 붙인다(말씀에 없는 내용 없음). 사물을 모르니 그림 없음(D75).
        # 본문은 화면에 보이고 소리로 읽히므로 금지어가 든 답은 뺀다 (NFR-DE-003, confirm_question 과 같은 규칙).
        said = " ".join(
            a.rstrip(" .") + "."
            for a in answers
            if not mood_of(a) and not wants_more(a) and not any(w in a for w in BANNED_WORDS)
        )
        draft = DiaryDraft.model_construct(
            body=said[:400] or "오늘 이야기를 나눴다.", mood=picked or "SO_SO", draw_objects=[]
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


def comfort(ctx: CoachContext, n: int) -> CoachReply:
    """힘든 말씀 뒤 n 번째 위로 말 (D94 바꿈, 11/23). 질문을 강요하지 않는다. AI 가 실패하면 고정 문장."""
    data = _data(ctx, n, max_turns=COMFORT_TURNS)
    try:
        out = llm.call_json("comfort", data, CoachReply)
    except (llm.LlmError, NotImplementedError):
        return CoachReply(text=COMFORT_LINES[(n - 1) % len(COMFORT_LINES)], suggestions=[], question_type="NONE")
    return out.model_copy(update={"suggestions": out.suggestions[:2], "question_type": "NONE"})


# ---------------------------------------------------------------- 심심이 잡담 (D106)
class ChatReply(CoachReply):
    """잡담 한 마디 — 회상·일기와 같은 대화 길(routers/sessions.py)로 다니고, 화면용 표정·가자는 화면·제목을 더 싣는다.
    잡담은 물음표 2개·120자까지라(ChatTurn 이 검사함) model_construct 로 만든다 — CoachReply 검사(물음표 1개)를
    다시 걸지 않게."""

    face: str | None = None  # 심심이 표정 (Sim 그림 이름)
    go: str | None = None  # DIARY | ALBUM | NEWS | MIND — 어르신이 가자고 하신 화면
    topic: str | None = None  # '지난 이야기' 제목


def _chat(text: str, face: str, question_type: str = "NONE", **extra: Any) -> ChatReply:
    return ChatReply.model_construct(text=text, suggestions=[], question_type=question_type, face=face, **extra)


CHAT_FALLBACK = _chat("아이고, 제가 잠깐 딴생각을 했어요. 다시 한 번 말씀해 주시겠어요?", "ask")
CHAT_CLOSING = _chat("오늘 이야기 즐거웠어요. 또 심심하시면 언제든 불러 주세요.", "hello", "CLOSING")
# 가자는 말('사진첩 열어 드릴게요') 뒤 말씀이 없을 때 — 그 말을 되풀이하지 않고 다음 이야기를 청한다 (11/25 잡담 잇기)
CHAT_MORE = _chat("또 하고 싶은 이야기나 궁금한 거 있으세요?", "smile")
CHAT_UNCLEAR = _chat(f"{UNCLEAR_LEAD} 다시 한 번 말씀해 주시겠어요?", "ask")  # 뜻 모를 말 뒤 (D112)
CHAT_RUDE_CLOSING = _chat(RUDE_CLOSING.text, "hello", "CLOSING")  # 잡담에서 거친 말 RUDE_END 번째 (D112)


def chat_reply(data: dict[str, Any]) -> tuple[CoachReply, str, bool]:
    """잡담 한 마디와 signal(NONE|LOW|RISK|BODY|STOP)·private. data = services/chat.data.

    위급(RISK 마음·BODY 몸)은 회상과 같은 코드 문장 — 호출자가 위로를 잇거나(RISK) 119 와 함께 끝낸다(BODY).
    STOP·closing 이면 그 말은 마무리 인사(질문 없음). AI 가 실패하면 고정 문장과 UNREAD (D14).
    """
    try:
        out = llm.call_json("chat_buddy", data, ChatTurn)
    except (llm.LlmError, NotImplementedError):
        return (CHAT_CLOSING if data.get("closing") else CHAT_FALLBACK), UNREAD, False
    signal = out.signal if any(t["speaker"] == "ELDER" for t in data["turns"]) else "NONE"  # 어르신 말 전 신호는 무시
    if signal in URGENT_CLOSINGS:
        return URGENT_CLOSINGS[signal], signal, out.private
    closing = signal == "STOP" or bool(data.get("closing"))
    go = None if closing or out.go == "NONE" else out.go
    reply = _chat(out.text, out.face, "CLOSING" if closing else "NONE", go=go, topic=out.topic or None)
    return reply, signal, out.private


def elder_reply(transcript: str) -> str:
    """어르신이 가족 일기에 말로 하신 답 → 어르신 말투 한 줄 40자 (11/23). 실패하면 하신 말 앞 40자(금지어는 뺀다)."""
    try:
        return llm.call_json("elder_reply", {"said": transcript}, ElderReply).text
    except (llm.LlmError, NotImplementedError):
        said = " ".join(transcript.split())
        for word in BANNED_WORDS:
            said = said.replace(word, "")
        return " ".join(said.split())[:REPLY_MAX]
