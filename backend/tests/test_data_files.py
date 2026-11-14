"""data/ 의 문제 은행·분류 목록이 서로 맞는지 (FR-AI-002·003, D39). 마지막 검사만 테스트 DB 를 쓴다."""

import json
import re

from sqlalchemy import func, select

from app.config import ROOT
from app.db import SessionLocal
from app.models import QuestionBank

DATA = ROOT / "data"
CODE = re.compile(r"^(RM|KH|TN|CM)-[a-z]+-\d{2}$")
PREFIX = {"REMEMBER": "RM", "KNOWHOW": "KH", "THEN_NOW": "TN", "COMMON": "CM"}


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text("utf-8"))


def active(questions: list[dict]) -> list[dict]:
    return [q for q in questions if q.get("is_active", True)]


def test_taxonomy_values():
    tax = load("taxonomy.json")
    for key in ("activity", "category"):
        values = tax[key]
        assert len(values) == len(set(values)), f"{key} 에 같은 값이 두 번"
        assert all(0 < len(v) <= 20 and v == v.strip() for v in values), f"{key} 는 20자 이내 (VARCHAR 20)"
        assert "none" not in values, "none 은 '맞는 값 없음' 표시라 목록에 넣지 않음"
    assert tax["_rules"] and all(isinstance(r, str) and r for r in tax["_rules"]), "고르는 기준 _rules"


def test_question_bank_rules():
    tax = load("taxonomy.json")
    questions = load("question_bank.json")["questions"]
    banned = load("banned_words.json")["words"]
    codes = [q["code"] for q in questions]
    assert len(codes) == len(set(codes)), "code 가 겹치면 seed 가 멈춤 (D39)"
    for q in questions:
        c = q["code"]
        assert CODE.match(c) and len(c) <= 30, c
        assert c.startswith(PREFIX[q["qtype"]] + "-"), f"{c}: 약자와 qtype 이 다름"
        if q["qtype"] == "KNOWHOW":
            assert q["activity"] in tax["activity"] and q["category"] is None, c
        elif q["qtype"] == "REMEMBER":
            assert q["category"] in tax["category"] and q["activity"] is None, c
        elif q["qtype"] == "THEN_NOW":  # activity 가 있으면 그 활동 사진에만, 없으면 아무 사진
            assert q["category"] is None and (q["activity"] is None or q["activity"] in tax["activity"]), c
        else:
            assert q["activity"] is None and q["category"] is None, c
        text = q["prompt_text"]
        # 120자 = 화면·소리로 나가는 AI 말 상한(CoachReply.text). 넘으면 문제 턴이 500 이 된다 (DB 는 200자)
        assert 0 < len(text) <= 120 and text.count("?") + text.count("？") <= 1, f"{c}: 질문은 한 번에 하나"
        assert not any(w in text for w in banned), f"{c}: 금지어 (NFR-DE-003)"
        assert q["choices"] is None or len(q["choices"]) == 2, f"{c}: 2지선다만"
        for ch in q["choices"] or []:
            assert 0 < len(ch.strip()) <= 12 and not any(w in ch for w in banned), f"{c}: 칩은 12자 이내·금지어 없음"
        assert 1 <= q["priority"] <= 9, c


def test_every_label_has_questions():
    """어떤 사진이든 문제 1개 이상 (FR-AI-002): 활동마다 노하우 2개+, 주제마다 떠올리기 1개+, none 사진용 공통 풀."""
    tax = load("taxonomy.json")
    questions = active(load("question_bank.json")["questions"])
    for a in tax["activity"]:
        assert sum(q["qtype"] == "KNOWHOW" and q["activity"] == a for q in questions) >= 2, f"노하우 부족: {a}"
    for c in tax["category"]:
        assert any(q["category"] == c for q in questions), f"떠올리기 없음: {c}"
    none_pool = [q for q in questions if q["qtype"] in ("THEN_NOW", "COMMON") and q["activity"] is None]
    assert len(none_pool) >= 20, "none 사진 공통 풀이 너무 적으면 14일 안에 같은 문제가 반복됨"


def test_family_fix_screen_uses_same_activities():
    """가족 '활동 고치기'(GROUP_004, D73)의 목록이 분류 목록과 같은 글자 — 다르면 고친 활동이 문제 은행과 안 맞는다."""
    tsx = (ROOT / "frontend" / "src" / "screens" / "family" / "GROUP_004.tsx").read_text("utf-8")
    listed = re.findall(r"'([^']+)'", tsx.split("const ACTIVITIES = [", 1)[1].split("]", 1)[0])
    assert listed == load("taxonomy.json")["activity"]


def test_seed_loads_question_bank():
    """seed 와 같은 방법(QuestionBank(**q))으로 넣었을 때 제약을 통과하고, choices 없음은 SQL NULL 로 저장."""
    questions = load("question_bank.json")["questions"]
    with SessionLocal() as db:
        db.add_all(QuestionBank(**q, created_by="test") for q in questions)
        db.flush()
        no_choices = db.scalar(select(func.count()).select_from(QuestionBank).where(QuestionBank.choices.is_(None)))
        assert no_choices == sum(q["choices"] is None for q in questions)
        db.rollback()
