"""LLM 어댑터 (D4, D14). 시그니처 고정: call_json(prompt_name, data, Schema) -> Schema

- 지시는 system(prompts/<name>.md)에만, 데이터는 JSON 문자열로 user 메시지에 (구분자 없음 → 위조 불가).
- 출력은 JSON 스키마로 강제하고 pydantic(Schema) 검사. 실패 1회 재시도, 재실패 시 LlmError (호출자가 고정 문장 사용).
- 호출당 로그 1줄: provider, prompt, ms, tokens (NFR-AN-003 원가 실측).
- LLM_PROVIDER=mock 이면 키 없이 고정 답을 돌려준다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import ROOT, settings

log = logging.getLogger("app.ai")
PROMPTS_DIR = ROOT / "backend" / "app" / "ai" / "prompts"

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    pass


def load_prompt(prompt_name: str) -> str:
    return (PROMPTS_DIR / f"{prompt_name}.md").read_text("utf-8")


def call_json(prompt_name: str, data: dict[str, Any], schema: type[T]) -> T:
    provider = settings.LLM_PROVIDER
    t0 = time.perf_counter()
    tokens = 0
    try:
        if provider == "mock":
            out = _mock(prompt_name, data, schema)
        elif provider == "anthropic":
            out, tokens = _anthropic(prompt_name, data, schema)
        else:
            raise LlmError(f"LLM_PROVIDER={provider} 는 지원하지 않습니다")
    finally:
        ms = int((time.perf_counter() - t0) * 1000)
        log.info("llm provider=%s prompt=%s ms=%d tokens=%d", provider, prompt_name, ms, tokens)
    return out


# ---------------------------------------------------------------- mock
_MOCK_QUESTIONS = [
    "이 사진은 언제 찍으신 거예요?",
    "그날 누구랑 같이 계셨어요?",
    "그때 기분이 어떠셨어요?",
    "거기서 제일 기억에 남는 건 뭐예요?",
    "그 음식은 어떻게 만드셨어요?",
    "그때랑 지금이랑 뭐가 제일 달라졌어요?",
    "요즘도 그런 날이 있으면 좋겠어요?",
]
_MOCK_CHIPS = [
    ["작년에요", "오래전에요", "기억 안 나요"],
    ["가족이랑요", "친구랑요"],
    ["좋았어요", "그저 그랬어요"],
]


def _mock(prompt_name: str, data: dict[str, Any], schema: type[T]) -> T:
    if prompt_name != "memory_coach":
        raise LlmError(f"mock 은 memory_coach 만 지원합니다 (요청: {prompt_name})")
    turn_no = int(data.get("turn_no", 1))
    if data.get("closing"):
        return schema.model_validate(
            {
                "text": "오늘 이야기 들려주셔서 고마워요. 내일 또 사진 들고 올게요.",
                "suggestions": [],
                "question_type": "CLOSING",
                "choice_mode": "TWO_BUTTONS",
            }
        )
    i = (turn_no - 1) % len(_MOCK_QUESTIONS)
    text = _MOCK_QUESTIONS[i]
    if turn_no == 1:
        honorific = data.get("elder_honorific", "어르신")
        text = f"{honorific}, 안녕하세요. 오늘은 이 사진 보면서 이야기해요. " + text
    return schema.model_validate(
        {
            "text": text,
            "suggestions": _MOCK_CHIPS[i % len(_MOCK_CHIPS)],
            "question_type": "RECALL",
            "choice_mode": "CHIPS",
        }
    )


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
        raise LlmError("ANTHROPIC_API_KEY 가 없습니다 (.env)")
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    system = load_prompt(prompt_name)
    user = json.dumps(data, ensure_ascii=False)
    json_schema = _simplify(schema.model_json_schema())
    tokens = 0
    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            response = client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": json_schema},
                },
            )
        except anthropic.APIError as e:
            log.warning("llm api error prompt=%s attempt=%d type=%s", prompt_name, attempt, type(e).__name__)
            raise LlmError(type(e).__name__) from e
        tokens += response.usage.input_tokens + response.usage.output_tokens
        if response.stop_reason == "refusal":
            raise LlmError("refusal")
        raw = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return schema.model_validate_json(raw), tokens
        except ValidationError as e:
            # D15: 원문은 로그에 남기지 않는다. prompt_name, attempt, len(raw) 만.
            log.warning("llm validation prompt=%s attempt=%d len=%d", prompt_name, attempt, len(raw))
            last_err = e
            system += "\n\n[주의] 직전 답이 규칙을 어겼습니다. 금지어 없이 질문 하나만, 추천 답변은 12자 이내 3개까지."
    raise LlmError(f"검증 실패: {type(last_err).__name__}")
