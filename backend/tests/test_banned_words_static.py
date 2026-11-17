"""주석·독스트링을 제외한 고정 문장의 금지어를 검사한다 (NFR-DE-003)."""

import ast
import json
import re

import pytest

from app.ai.schemas import BANNED_WORDS
from app.config import ROOT

# 낱말 속 우연과 사용자에게 출력되지 않는 코드용 문자열만 정확한 파일·문자열로 예외 처리한다.
EXCEPTIONS = {
    ("backend/app/ai/coach.py", "저하고 이야기 나누실까요?"),
    ("backend/app/ai/coach.py", "틀렸어요"),  # 음성 입력 비교용. 화면·소리로 출력하지 않는다.
    ("backend/app/ai/llm.py", "검증 실패: "),  # 내부 예외의 문자열 조각
}
TS_STRING = re.compile(r""""(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`""")
KNOWN_MOOD_TEXT = (
    "지난 2주 동안 스스로가 못났다거나 실패했다고 느끼거나, 자신이나 가족을 실망시켰다고 느낀 날이 얼마나 있었어요?"
)


def python_strings(path):
    source = path.read_text("utf-8-sig")
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.lineno, node.value


def typescript_strings(path):
    source = path.read_text("utf-8")
    # 문자열 내부의 //와 /*는 보존한다. 주석을 같은 길이 공백으로 바꿔 줄 번호도 보존한다.
    tokens = re.compile(TS_STRING.pattern + r"|//[^\n]*|/\*[\s\S]*?\*/")
    for match in tokens.finditer(source):
        value = match.group()
        if value.startswith(("//", "/*")):
            continue
        yield source.count("\n", 0, match.start()) + 1, value[1:-1]


def json_strings(value):
    if isinstance(value, str):
        yield 1, value
    elif isinstance(value, dict):
        for child in value.values():
            yield from json_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_strings(child)


def fixed_text_paths():
    frontend = ROOT / "frontend/src"
    paths = sorted((ROOT / "backend/app").rglob("*.py"))
    paths += sorted((frontend / "screens").rglob("*.tsx"))
    paths += sorted((frontend / "components").rglob("*.tsx"))
    paths += [frontend / "lib/audio.ts", frontend / "lib/moodCheck.ts", ROOT / "data/question_bank.json"]
    return paths


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(
            path,
            id=path.relative_to(ROOT).as_posix(),
        )
        for path in fixed_text_paths()
    ],
)
def test_fixed_user_text_has_no_banned_words(path):
    hits = []
    relative = path.relative_to(ROOT).as_posix()
    if path.suffix == ".py":
        strings = python_strings(path)
    elif path.suffix == ".json":
        strings = json_strings(json.loads(path.read_text("utf-8")))
    else:
        strings = typescript_strings(path)
    elder = (
        "screens/elder/" in relative
        or "components/VoiceSession/" in relative
        or relative.endswith(("lib/audio.ts", "lib/moodCheck.ts"))
        or relative.startswith("backend/app/ai/")
        or relative
        in {
            "backend/app/routers/elder.py",
            "backend/app/routers/sessions.py",
            "backend/app/routers/diaries.py",
            "backend/app/routers/mood.py",
            "backend/app/routers/stt.py",
            "backend/app/routers/devices.py",
            "backend/app/deps.py",
            "backend/app/errors.py",
        }
    )
    for line, value in strings:
        if (relative, value) in EXCEPTIONS:
            continue
        if relative == "frontend/src/lib/moodCheck.ts" and value == KNOWN_MOOD_TEXT:
            continue  # 알려진 문장만 별도 strict xfail 검사에서 확인한다.
        words = [word for word in BANNED_WORDS if word in value]
        if elder and "실패" in value:
            words.append("실패")
        if words:
            hits.append(f"{relative}:{line} ({', '.join(words)})")
    assert not hits, "\n".join(hits)


@pytest.mark.xfail(strict=True, reason="frontend/src/lib/moodCheck.ts:21 어르신 마음 체크에 '실패' 포함")
def test_known_mood_prompt_has_no_failure_word():
    path = ROOT / "frontend/src/lib/moodCheck.ts"
    assert not any(value == KNOWN_MOOD_TEXT and "실패" in value for _, value in typescript_strings(path))


def test_new_mood_violation_is_not_masked_by_known_sentence(monkeypatch):
    monkeypatch.setitem(globals(), "typescript_strings", lambda path: iter([(21, KNOWN_MOOD_TEXT), (22, "점수")]))
    with pytest.raises(AssertionError, match="점수"):
        test_fixed_user_text_has_no_banned_words(ROOT / "frontend/src/lib/moodCheck.ts")
