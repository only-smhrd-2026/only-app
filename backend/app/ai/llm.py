"""LLM 어댑터 (D4, D14). 시그니처 고정: call_json(prompt_name, data, Schema) -> Schema (사진 분류만 image= 를 더 넘김)

- 지시는 system(prompts/<name>.md)에만, 데이터는 JSON 문자열로 user 메시지에 (구분자 없음 → 위조 불가).
- 출력은 JSON 스키마로 강제하고 pydantic(Schema) 검사. 실패 1회 재시도, 재실패 시 LlmError (호출자가 고정 문장 사용).
- 시도당 시간 상한: 말하기 턴 6초, 그 밖(일기 초안 등) 15초. SDK 재시도 없음 → API 오류·시간 초과도 바로 LlmError.
- 금지어 목록(data/banned_words.json)은 모든 프롬프트 끝에 자동으로 붙는다 (load_prompt).
- 호출당 로그 1줄: provider, prompt, ms, tokens (NFR-AN-003 원가 실측).
- LLM_PROVIDER=mock 이면 키 없이 고정 답을 돌려준다.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.schemas import BANNED_WORDS, TAXONOMY
from app.config import (
    CLASSIFY_PER_DAY,
    LLM_CHAT_PER_DAY,
    LLM_FAIL_ALERT,
    LLM_FAMILY_PER_DAY,
    LLM_PER_DAY,
    ROOT,
    WEEKLY_CARDS_MAX,
    settings,
)
from app.security import daily_allowed

log = logging.getLogger("app.ai")
PROMPTS_DIR = ROOT / "backend" / "app" / "ai" / "prompts"

# 시도당 시간 상한(초). 말하기 턴은 화면이 15초에 포기하므로 6초 × 최대 2번(검증 재시도) 안에 끝나야
# 고정 문장으로라도 대화가 이어진다(D14). 일기 초안은 확인 화면이 기다리므로 15초 × 최대 2번 (D36).
# 가족 일기 질문(D58)·어제 이야기 첫 질문(D77)도 화면에서 바로 기다린다
TURN_PROMPTS = {"memory_coach", "diary_buddy", "family_buddy", "story_question", "comfort", "chat_buddy"}
ELDER_TALK = {"memory_coach", "diary_buddy", "chat_buddy", "comfort"}  # 끝에 prompts/_elder_common.md 를 붙인다 (D114)
FAMILY_PROMPTS = {"family_buddy", "family_draft"}  # 가족이 부르는 것 — 하루 몫을 따로 센다 (LLM_FAMILY_PER_DAY)
TURN_TIMEOUT_SEC = 6.0
OTHER_TIMEOUT_SEC = 15.0

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    pass


class LlmRefused(LlmError):
    """모델이 답했지만 쓸 수 없음(거절·검사 2번 실패). 다시 불러도 같을 가능성이 높다.

    LlmError 의 자식이라 기존 호출자는 그대로 고정 문장으로 간다. 사진 분류만 이것을 '분류 끝(none)'으로 본다 (D71).
    """


def load_prompt(prompt_name: str) -> str:
    """prompts/<name>.md + 금지어 목록 (NFR-DE-003). 금지어는 data/banned_words.json 한 곳에서 관리한다."""
    rule = (
        "\n\n# 금지어 (코드가 검사한다)\n다음 말은 어떤 경우에도 쓰지 않는다. 어르신 말에 들어 있으면 그 부분은 "
        f"다른 말로 바꾸거나 뺀다: {', '.join(BANNED_WORDS)}"
    )
    text = (PROMPTS_DIR / f"{prompt_name}.md").read_text("utf-8")
    if prompt_name in ELDER_TALK:  # 어르신 대화 공통 규칙·위급 판단 기준은 한 파일에서만 고친다 (D114)
        text += "\n\n" + (PROMPTS_DIR / "_elder_common.md").read_text("utf-8")
    if prompt_name == "classify_photo":  # 고르는 기준·목록은 taxonomy.json 한 곳 — 정답표 안내와 같은 글 (D71)
        text += "\n\n# 분류 기준\n" + "\n".join(f"- {r}" for r in TAXONOMY["_rules"])
        text += f"\n\n활동 목록: {', '.join(TAXONOMY['activity'])}\n주제 목록: {', '.join(TAXONOMY['category'])}"
    return text + rule


def call_json(
    prompt_name: str,
    data: dict[str, Any],
    schema: type[T],
    *,
    image: bytes | None = None,
    timeout: float | None = None,
) -> T:
    """image = JPEG 바이트(사진 분류만, data 앞에 붙는다). timeout = 시도당 시간 상한(초), 없으면 프롬프트별 기본."""
    provider = settings.LLM_PROVIDER
    t0 = time.perf_counter()
    tokens = 0
    # 사진 분류는 대화와 따로 센다 — 사진을 많이 올려도 어르신 대화가 고정 문장으로 바뀌지 않게 (D71).
    # 심심이 잡담도 따로 — 잡담을 많이 해도 회상·일기 몫은 남는다 (D106)
    kind, cap = {
        "classify_photo": ("classify", CLASSIFY_PER_DAY),
        "chat_buddy": ("llm_chat", LLM_CHAT_PER_DAY),
    }.get(prompt_name, ("llm", LLM_PER_DAY))
    try:
        if provider == "mock":
            out = _mock(prompt_name, data, schema)
        elif provider == "anthropic":
            # 가족 일기 동무는 하루 몫의 절반까지만 — 가입한 누구나 부를 수 있어도 어르신 대화 몫은 남는다 (11/19)
            if prompt_name in FAMILY_PROMPTS and not daily_allowed("llm_family", LLM_FAMILY_PER_DAY):
                log.warning("llm family share prompt=%s", prompt_name)
                raise LlmError("가족 몫 상한")
            if not daily_allowed(kind, cap):
                log.warning("llm daily cap prompt=%s", prompt_name)
                raise LlmError("하루 상한")  # 호출자가 고정 문장으로 이어 간다 (D14·D46)
            out, tokens = _anthropic(prompt_name, data, schema, image, timeout)
        else:
            raise LlmError(f"LLM_PROVIDER={provider} 는 지원하지 않습니다")
    except LlmRefused:  # 모델은 답했다 — 장애가 아니다
        raise
    except LlmError:
        _failed(provider, prompt_name)
        raise
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("llm provider=%s prompt=%s ms=%d tokens=%d", provider, prompt_name, ms, tokens)
    global _fail_streak
    _fail_streak = 0
    return out


# 연달아 실패한 AI 호출 수 (11/26 — 크레딧 부족·분당 상한·하루 상한이면 고정 문장으로 이어 가서 겉으로는 멀쩡해 보인다).
# 성공하면 0. ponytail: 프로세스 메모리(워커 1개, D9) — 다시 켜면 0, 여러 스레드가 동시에 더해도 대략이면 된다
_fail_streak = 0


def fail_streak() -> int:
    return _fail_streak


def _failed(provider: str, prompt_name: str) -> None:
    global _fail_streak
    if provider != "anthropic":  # mock 은 일기 프롬프트를 늘 실패로 넘긴다 — 장애가 아니다
        return
    _fail_streak += 1
    if _fail_streak == LLM_FAIL_ALERT:  # 한 번만 — 계속 실패해도 로그가 쌓이지 않게
        log.error("llm failing streak=%d prompt=%s", _fail_streak, prompt_name)


# ---------------------------------------------------------------- mock
_MOCK_QUESTIONS = [
    "이 사진 보니 어떠세요?",
    "그날 누구랑 같이 계셨어요?",
    "그때 기분이 어떠셨어요?",
    "거기서 제일 기억에 남는 건 뭐예요?",
    "그 음식은 어떻게 만드셨어요?",
    "그때랑 지금이랑 뭐가 제일 달라졌어요?",
    "요즘도 그런 날이 있으면 좋겠어요?",
]
_MOCK_CHIPS = [
    ["좋아요", "글쎄요", "기억 안 나요"],
    ["가족이랑요", "친구랑요"],
    ["좋았어요", "그저 그랬어요"],
]


_MOCK_GO = (("일기", "DIARY"), ("사진첩", "ALBUM"), ("소식", "NEWS"), ("마음", "MIND"))
_MOCK_GO_TEXT = {"DIARY": "일기 쓰기", "ALBUM": "사진첩", "NEWS": "가족 소식", "MIND": "마음 체크"}


def _mock_chat(data: dict[str, Any]) -> dict[str, Any]:
    """잡담 mock — 가자는 낱말(일기·사진첩·소식·마음 + 가자·보여·열어·할래)이면 그 화면, 아니면 고정 맞장구."""
    turns = data.get("turns") or []
    said = turns[-1]["text"] if turns and turns[-1].get("speaker") == "ELDER" else ""
    base = {"face": "smile", "go": "NONE", "topic": "심심이랑 나눈 이야기", "signal": "NONE", "private": False}
    if data.get("closing"):
        return base | {"text": "오늘 이야기 즐거웠어요. 또 심심하시면 언제든 불러 주세요."}
    if not said:
        hon = data.get("elder_honorific", "어르신")
        return base | {"face": "hello", "text": f"{hon}, 반가워요! 오늘은 뭐 하셨어요?"}
    if any(w in said for w in ("가자", "보여", "열어", "할래", "쓰자")):
        for word, go in _MOCK_GO:
            if word in said:
                return base | {"face": "thumbs", "go": go, "text": f"좋아요! {_MOCK_GO_TEXT[go]} 열어 드릴게요."}
    return base | {"face": "joy", "text": "우와, 그러셨군요! 조금 더 들려주세요."}


def _mock(prompt_name: str, data: dict[str, Any], schema: type[T]) -> T:
    if prompt_name == "weekly_summary":  # 어르신 답을 그대로 따온 카드 — 키 없는 PC 에서도 카드가 보이게 (D62)
        cards = [
            {"ref": p["ref"], "answer": f"'{p['said'][:30]}'라고 하셨어요.", "quote": p["said"][:30]}
            for p in data["pairs"][:WEEKLY_CARDS_MAX]
        ]
        return schema.model_validate({"cards": cards})
    if prompt_name == "story_facts":  # 첫 답을 그대로 따온 기억 하나 — 키 없는 PC 에서도 이어 묻기가 돌게 (D77)
        facts = [
            {"ref": p["ref"], "kind": "EVENT", "fact": f"'{p['said'][:30]}'라고 하셨어요.", "quote": p["said"][:30]}
            for p in data["pairs"][:1]
        ]
        return schema.model_validate({"facts": facts})
    if prompt_name == "memory_card":  # 가장 긴 답을 그대로 따온 요약 — 키 없는 PC 에서도 회상 카드가 보이게 (D115)
        said = max((p["said"] for p in data["pairs"]), key=len)
        return schema.model_validate({"summary": f"'{said[:40]}' 하고 이야기하셨어요.", "quote": said[:40]})
    if prompt_name == "story_question":
        text = f"{data.get('elder_honorific', '어르신')}, {data['when']} 들려주신 이야기 생각나요. 그 뒤로 어떠셨어요?"
        return schema.model_validate({"text": text, "suggestions": ["좋았어요", "그저 그래요"], "signal": "NONE"})
    if prompt_name == "chat_buddy":  # 키 없는 PC 에서도 잡담 화면·화면 이동을 눌러 볼 수 있게 (D106)
        return schema.model_validate(_mock_chat(data))
    if prompt_name != "memory_coach":  # 일기(diary_*·family_*)는 coach 의 고정 문장으로 이어 간다
        raise LlmError(f"mock 은 memory_coach·weekly_summary·story_*·memory_card 만 지원합니다 (요청: {prompt_name})")
    turn_no = int(data.get("turn_no", 1))
    if data.get("closing"):
        text = "오늘 이야기 들려주셔서 고마워요. 모아서 가족들한테 전해 드릴게요."
        return schema.model_validate({"text": text, "suggestions": [], "signal": "NONE"})
    if data.get("quiz"):  # 맞장구만 — 문제 문장은 coach 가 문제 은행 원문으로 붙인다
        return schema.model_validate(
            {"text": "아, 그러셨군요.", "suggestions": ["생각나요", "잘 모르겠어요"], "signal": "NONE"}
        )
    i = (turn_no - 1) % len(_MOCK_QUESTIONS)
    text = _MOCK_QUESTIONS[i]
    if turn_no == 1:  # 날짜·요일은 묻지 않고 첫 말에 섞어 알려 준다 (FR-AI-003)
        today = f"오늘은 {data['today']}이에요. " if data.get("today") else ""
        text = f"{data.get('elder_honorific', '어르신')}, {today}{text}"
    return schema.model_validate({"text": text, "suggestions": _MOCK_CHIPS[i % len(_MOCK_CHIPS)], "signal": "NONE"})


# ------------------------------------------------------------ anthropic
def _simplify(schema: dict[str, Any]) -> dict[str, Any]:
    """pydantic JSON 스키마 → 구조화 출력용 (모든 속성 required, additionalProperties false, 제약 키 제거)."""
    drop = {"title", "default", "maxItems", "minItems", "maxLength", "minLength"}
    out = {k: v for k, v in schema.items() if k not in drop}
    if out.get("type") == "object" and "properties" in out:
        out["properties"] = {k: _simplify(v) for k, v in out["properties"].items()}
        out["required"] = list(out["properties"].keys())
        out["additionalProperties"] = False
    if "items" in out and isinstance(out["items"], dict):
        out["items"] = _simplify(out["items"])
    if "$defs" in out:  # 중첩 모델(주간 카드 목록) — 구조화 출력은 안쪽 객체에도 같은 규칙을 요구한다
        out["$defs"] = {k: _simplify(v) for k, v in out["$defs"].items()}
    return out


def _anthropic(
    prompt_name: str, data: dict[str, Any], schema: type[T], image: bytes | None = None, timeout: float | None = None
) -> tuple[T, int]:
    import anthropic  # 키가 있을 때만 쓰는 의존성

    if not settings.ANTHROPIC_API_KEY:
        log.warning("llm no api key prompt=%s", prompt_name)  # 고정 문장으로 이어 가지만 운영에서는 알아야 한다
        raise LlmError("ANTHROPIC_API_KEY 가 없습니다 (.env)")
    # SDK 재시도는 끈다: 기본값(재시도 2회, Retry-After 만큼 대기)이면 멈춘 호출 하나가 위 시간 상한을 훌쩍 넘긴다.
    # API 오류·시간 초과는 바로 LlmError → 호출자가 고정 문장(턴)이나 글만 초안(일기)으로 이어 간다.
    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY, base_url=settings.ANTHROPIC_BASE_URL or None, max_retries=0
    )
    timeout = timeout or (TURN_TIMEOUT_SEC if prompt_name in TURN_PROMPTS else OTHER_TIMEOUT_SEC)
    system = load_prompt(prompt_name)
    user: Any = json.dumps(data, ensure_ascii=False)
    if image is not None:  # 사진은 글(데이터) 앞에. 사진 속 글자도 지시가 아니라 데이터다 (D14, classify_photo.md)
        b64 = base64.standard_b64encode(image).decode("ascii")
        user = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
            {"type": "text", "text": user},
        ]
    json_schema = _simplify(schema.model_json_schema())
    tokens = 0
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            response = client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=1024,  # 일기 초안(3~5문장 JSON)도 잘리지 않게. 과금은 실제로 쓴 만큼만
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": json_schema},
                },
                timeout=timeout,
            )
        except anthropic.APIError as e:  # 400 도 여기 — 크레딧 부족도 400 이라 '다시 해도 같다'로 보지 않는다
            # API 오류 문장도 남긴다(11/24: 크레딧 부족이 type 만으로는 안 보였다). 요청 글은 안 들어간다 (D15)
            log.warning(
                "llm api error prompt=%s attempt=%d type=%s msg=%.200s",
                prompt_name,
                attempt,
                type(e).__name__,
                getattr(e, "message", ""),
            )
            raise LlmError(type(e).__name__) from e
        tokens += response.usage.input_tokens + response.usage.output_tokens
        if response.stop_reason == "refusal":
            log.warning("llm refusal prompt=%s attempt=%d", prompt_name, attempt)
            raise LlmRefused("refusal")
        raw = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return schema.model_validate_json(raw), tokens
        except ValidationError as e:
            # D15: 원문은 로그에 남기지 않는다. prompt_name, attempt, len(raw) 만.
            log.warning("llm validation prompt=%s attempt=%d len=%d", prompt_name, attempt, len(raw))
            last_err = e
            system += "\n\n[주의] 직전 답이 출력 규칙(금지어·물음표·글자 수·개수)을 어겼습니다. 규칙대로 다시 답하세요."
    raise LlmRefused(f"검증 실패: {type(last_err).__name__}")
