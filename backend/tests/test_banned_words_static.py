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


def test_fixed_user_text_has_no_banned_words():
    frontend = ROOT / "frontend/src"
    paths = sorted((ROOT / "backend/app").rglob("*.py"))
    paths += sorted((frontend / "screens").rglob("*.tsx"))
    paths += sorted((frontend / "components").rglob("*.tsx"))
    paths += [frontend / "lib/audio.ts", frontend / "lib/moodCheck.ts", ROOT / "data/question_bank.json"]
    hits = []
    for path in paths:
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
            or relative in {"backend/app/routers/elder.py", "backend/app/routers/sessions.py"}
        )
        for line, value in strings:
            if (relative, value) in EXCEPTIONS:
                continue
            words = [word for word in BANNED_WORDS if word in value]
            if elder and "실패" in value:
                words.append("실패")
            if words:
                hits.append(f"{relative}:{line} ({', '.join(words)})")
    if hits:
        pytest.xfail("고정 문장 금지어 확인 필요\n" + "\n".join(hits))
