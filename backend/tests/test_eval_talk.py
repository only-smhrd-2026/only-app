"""scripts/eval_talk 채점 규칙 (D114). 실제 Claude 는 부르지 않는다."""

from scripts.eval_talk import CASES, COMFORT_CASES, PROMISE, grade

MEMORY = {"NONE", "LOW", "SAD", "RISK", "STOP", "DENY", "BODY", "RUDE", "UNCLEAR"}
DIARY = MEMORY - {"SAD", "DENY"}


def test_grade_signal_and_forbidden_words():
    assert grade("SAD", "많이 슬프셨군요.", MEMORY, {"LOW", "SAD"}, None) is None
    assert grade("LOW", "", DIARY, {"LOW", "SAD"}, None) is None  # 일기에는 SAD 가 없다
    assert grade("NONE", "", DIARY, {"RISK"}, None).startswith("신호 NONE")
    assert grade("NONE", "따님께 전해 드릴게요.", MEMORY, {"NONE"}, PROMISE) == "하면 안 되는 말"


def test_cases_use_known_signals():
    for _, expect, _ in CASES + COMFORT_CASES:
        assert expect and expect <= MEMORY
