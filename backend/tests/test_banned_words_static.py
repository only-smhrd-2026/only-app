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
# 마음 체크 6번 = PHQ-9 공식 한국어판 문구 그대로(D66). 검증된 설문은 바꾸면 타당성이 깨져서
# NFR-DE-003 '실패' 금지의 예외로 둔다(11/17 사용자 결정 — 5주차 문서 고칠 목록)
KNOWN_MOOD_TEXT = (
    "지난 2주 동안 스스로가 못났다거나 실패했다고 느끼거나, 자신이나 가족을 실망시켰다고 느낀 날이 얼마나 있었어요?"
)
EXCEPTIONS.add(("frontend/src/lib/moodCheck.ts", KNOWN_MOOD_TEXT))


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


def _strings(path):
    if path.suffix == ".py":
        return python_strings(path)
    if path.suffix == ".json":
        return json_strings(json.loads(path.read_text("utf-8")))
    return typescript_strings(path)


def _elder_facing(relative: str) -> bool:
    return (
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
            "backend/app/services/care.py",
            "backend/app/deps.py",
            "backend/app/errors.py",
        }
    )


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
    elder = _elder_facing(relative)
    for line, value in _strings(path):
        if (relative, value) in EXCEPTIONS:
            continue
        words = [word for word in BANNED_WORDS if word in value]
        if elder and "실패" in value:
            words.append("실패")
        if words:
            hits.append(f"{relative}:{line} ({', '.join(words)})")
    assert not hits, "\n".join(hits)


def test_elder_never_hears_family_was_told():
    """어르신께 '가족에게 알렸어요·알릴게요'라고 하지 않는다 — 가족 알림은 그대로 간다 (11/23 사용자, D94 바꿈).

    처음 연결 때의 동의 안내('힘든 말씀을 하시면 가족에게도 알려요')는 고지라 '알려'로 남는다.
    """
    hits = [
        f"{path.relative_to(ROOT).as_posix()}:{line}"
        for path in fixed_text_paths()
        if _elder_facing(path.relative_to(ROOT).as_posix())
        for line, value in _strings(path)
        if "알렸" in value or "알릴게" in value
    ]
    assert not hits, "\n".join(hits)


def test_mood_exception_is_still_the_official_sentence():
    """예외는 공식 문구 그 문장 하나 — 문구가 바뀌면 예외도 다시 본다(낡은 예외가 다른 문장을 덮지 않게)."""
    path = ROOT / "frontend/src/lib/moodCheck.ts"
    assert any(value == KNOWN_MOOD_TEXT for _, value in typescript_strings(path))


def test_new_mood_violation_is_not_masked_by_known_sentence(monkeypatch):
    monkeypatch.setitem(globals(), "typescript_strings", lambda path: iter([(21, KNOWN_MOOD_TEXT), (22, "점수")]))
    with pytest.raises(AssertionError, match="점수"):
        test_fixed_user_text_has_no_banned_words(ROOT / "frontend/src/lib/moodCheck.ts")
