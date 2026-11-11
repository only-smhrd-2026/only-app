"""LLM 어댑터 (D4, D14). 시그니처 고정: call_json(prompt_name, data, Schema) -> Schema

- 지시는 system(prompts/<name>.md)에만, 데이터는 JSON 문자열로 user 메시지에 (구분자 없음 → 위조 불가).
- 출력은 JSON 스키마로 강제하고 pydantic(Schema) 검사. 실패 1회 재시도, 재실패 시 LlmError (호출자가 고정 문장 사용).
- 시도당 시간 상한: 말하기 턴 6초, 그 밖(일기 초안 등) 15초. SDK 재시도 없음 → API 오류·시간 초과도 바로 LlmError.
- 금지어 목록(data/banned_words.json)은 모든 프롬프트 끝에 자동으로 붙는다 (load_prompt).
- 호출당 로그 1줄: provider, prompt, ms, tokens (NFR-AN-003 원가 실측).
- LLM_PROVIDER=mock 이면 키 없이 고정 답을 돌려준다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.schemas import BANNED_WORDS
from app.config import LLM_PER_DAY, ROOT, settings
from app.security import daily_allowed

log = logging.getLogger("app.ai")
PROMPTS_DIR = ROOT / "backend" / "app" / "ai" / "prompts"

# 시도당 시간 상한(초). 말하기 턴은 화면이 15초에 포기하므로 6초 × 최대 2번(검증 재시도) 안에 끝나야
# 고정 문장으로라도 대화가 이어진다(D14). 일기 초안은 확인 화면이 기다리므로 15초 × 최대 2번 (D36).
TURN_PROMPTS = {"memory_coach", "diary_buddy"}
TURN_TIMEOUT_SEC = 6.0
OTHER_TIMEOUT_SEC = 15.0

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    pass


def load_prompt(prompt_name: str) -> str:
    """prompts/<name>.md + 금지어 목록 (NFR-DE-003). 금지어는 data/banned_words.json 한 곳에서 관리한다."""
    rule = (
        "\n\n# 금지어 (코드가 검사한다)\n다음 말은 어떤 경우에도 쓰지 않는다. 어르신 말에 들어 있으면 그 부분은 "
        f"다른 말로 바꾸거나 뺀다: {', '.join(BANNED_WORDS)}"
    )
    return (PROMPTS_DIR / f"{prompt_name}.md").read_text("utf-8") + rule


def call_json(prompt_name: str, data: dict[str, Any], schema: type[T]) -> T:
    provider = settings.LLM_PROVIDER
    t0 = time.perf_counter()
    tokens = 0
    try:
        if provider == "mock":
            out = _mock(prompt_name, data, schema)
        elif provider == "anthropic":
            if not daily_allowed("llm", LLM_PER_DAY):
                log.warning("llm daily cap prompt=%s", prompt_name)
                raise LlmError("하루 상한")  # 호출자가 고정 문장으로 이어 간다 (D14·D46)
            out, tokens = _anthropic(prompt_name, data, schema)
        else:
            raise LlmError(f"LLM_PROVIDER={provider} 는 지원하지 않습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("llm provider=%s prompt=%s ms=%d tokens=%d", provider, prompt_name, ms, tokens)
    return out


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


def _mock(prompt_name: str, data: dict[str, Any], schema: type[T]) -> T:
    if prompt_name != "memory_coach":  # 일기(diary_buddy·diary_draft)는 coach 의 고정 문장으로 이어 간다
        raise LlmError(f"mock 은 memory_coach 만 지원합니다 (요청: {prompt_name})")
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
    return out


def _anthropic(prompt_name: str, data: dict[str, Any], schema: type[T]) -> tuple[T, int]:
    import anthropic  # 키가 있을 때만 쓰는 의존성

    if not settings.ANTHROPIC_API_KEY:
        log.warning("llm no api key prompt=%s", prompt_name)  # 고정 문장으로 이어 가지만 운영에서는 알아야 한다
        raise LlmError("ANTHROPIC_API_KEY 가 없습니다 (.env)")
    # SDK 재시도는 끈다: 기본값(재시도 2회, Retry-After 만큼 대기)이면 멈춘 호출 하나가 위 시간 상한을 훌쩍 넘긴다.
    # API 오류·시간 초과는 바로 LlmError → 호출자가 고정 문장(턴)이나 글만 초안(일기)으로 이어 간다.
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=0)
    timeout = TURN_TIMEOUT_SEC if prompt_name in TURN_PROMPTS else OTHER_TIMEOUT_SEC
    system = load_prompt(prompt_name)
    user = json.dumps(data, ensure_ascii=False)
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
        except anthropic.APIError as e:
            log.warning("llm api error prompt=%s attempt=%d type=%s", prompt_name, attempt, type(e).__name__)
            raise LlmError(type(e).__name__) from e
        tokens += response.usage.input_tokens + response.usage.output_tokens
        if response.stop_reason == "refusal":
            log.warning("llm refusal prompt=%s attempt=%d", prompt_name, attempt)
            raise LlmError("refusal")
        raw = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return schema.model_validate_json(raw), tokens
        except ValidationError as e:
            # D15: 원문은 로그에 남기지 않는다. prompt_name, attempt, len(raw) 만.
            log.warning("llm validation prompt=%s attempt=%d len=%d", prompt_name, attempt, len(raw))
            last_err = e
            system += "\n\n[주의] 직전 답이 출력 규칙(금지어·물음표·글자 수·개수)을 어겼습니다. 규칙대로 다시 답하세요."
    raise LlmError(f"검증 실패: {type(last_err).__name__}")
