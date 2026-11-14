"""주간 요약 AI-09 (#56, D62) — 카드가 어르신 말에서만 나오는지, 빼야 할 대화가 빠지는지, 규칙 검사·실패 처리.

유료 API 는 부르지 않는다: mock 은 어르신 답을 그대로 따온 카드를 내고, 규칙 검사는 모델 출력을 흉내 내서 본다.
"""

import json
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.ai import llm
from app.ai import weekly as weekly_ai
from app.ai.schemas import WeeklyCard, WeeklyCards
from app.config import TZ, WEEKLY_CARDS_MAX
from app.db import SessionLocal
from app.models import TalkSession, WeeklySummary
from app.services import weekly
from tests.conftest import add_photos, make_room, signup

NOW = datetime(2026, 11, 15, 19, tzinfo=TZ)  # 일요일 19:00 — 집계 창은 11/8 19:00 ~ 11/15 19:00
WEEK = date(2026, 11, 9)


def _room(client) -> int:
    signup(client)
    return make_room(client)["room_id"]


def _talk(db, room_id, day, qa, *, kind="MEMORY", photo_id=None, private=False, flag="NONE", confidence=0.9):
    """AI 질문 → 어르신 답을 번갈아 넣은 대화 하나 (턴 모양은 schema.sql sessions 주석)."""
    turns = []
    for question, said in qa:
        turns.append({"turn_no": len(turns) + 1, "speaker": "AI", "text": question})
        turns.append(
            {
                "turn_no": len(turns) + 1,
                "speaker": "ELDER",
                "text": said,
                "stt_confidence": confidence,
                "reply_to_turn_no": len(turns),
            }
        )
    db.add(
        TalkSession(
            session_id=uuid.uuid4(),
            room_id=room_id,
            kind=kind,
            photo_id=photo_id,
            input_mode="VOICE",
            started_at=datetime(2026, 11, day, 10, tzinfo=TZ),
            private_flag=private,
            emotion_flag=flag,
            turns=turns,
        )
    )


def _summarize(room_id) -> WeeklySummary:
    with SessionLocal() as db:
        weekly.build(db, room_id, NOW)
        weekly_ai.summarize(db, room_id, WEEK)
        return db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id))


def _no_ai(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("AI 를 부르면 안 된다")

    monkeypatch.setattr(llm, "call_json", fail)


def test_cards_come_from_elder_words_and_show_in_weekly(client):
    """mock: 질문은 대화 원문 그대로, 답은 어르신 말을 따온 전달형 문장, 사진 주소·날짜·근거 턴이 붙는다."""
    room_id = _room(client)
    photo_id = add_photos(room_id, 1)[0]
    with SessionLocal() as db:
        _talk(db, room_id, 10, [("잔칫상에 뭐가 올라갔어요?", "홍어랑 잡채랑 식혜가 올라갔지")], photo_id=photo_id)
        db.commit()
    row = _summarize(room_id)
    assert (row.rule_check_passed, row.model_version) == (True, "mock")
    out = client.get(f"/api/rooms/{room_id}/weekly").json()
    (card,) = out["qa_list"]
    assert card["question"] == "잔칫상에 뭐가 올라갔어요?"
    assert card["answer"] == "'홍어랑 잡채랑 식혜가 올라갔지'라고 하셨어요."
    assert card["photo_id"] == photo_id
    assert card["photo_url"].startswith(f"/api/media/rooms/{room_id}/")
    assert (card["date"], card["source_turns"]) == ("2026-11-10", [2])
    assert out["notes"] is None


def test_private_low_unsure_short_and_diary_talk_stay_out(client):
    """비밀 부탁·기운 없음·잘못 들었을 수 있는 말·'네'·일기 대화는 카드에 안 나온다. 기운 없음은 한 줄만."""
    room_id = _room(client)
    with SessionLocal() as db:
        _talk(db, room_id, 9, [("누구랑 가셨어요?", "큰오빠랑 둘이 갔지")])
        _talk(db, room_id, 10, [("요즘 어떠세요?", "허리가 아픈데 애들한테는 말하지 마")], private=True)
        _talk(db, room_id, 11, [("오늘은 어떠세요?", "요즘은 통 기운이 없어")], flag="LOW")
        _talk(db, room_id, 12, [("어디였어요?", "글쎄 어디였더라 바닷가였나")], confidence=0.5)
        _talk(db, room_id, 13, [("기억나세요?", "네")], kind="ALBUM")
        _talk(db, room_id, 14, [("오늘 뭐 하셨어요?", "시장에 다녀왔어")], kind="DIARY")
        db.commit()
    row = _summarize(room_id)
    assert [card["question"] for card in row.qa_list] == ["누구랑 가셨어요?"]
    assert row.notes == {"lines": [weekly_ai.CARE_LINE]}


@pytest.mark.parametrize(
    ("flag", "private", "care"),
    [("NONE", False, False), ("LOW", False, True), ("LOW", True, False), ("RISK", True, True)],
)
def test_care_line_without_content(client, monkeypatch, flag, private, care):
    """기운 없음·위급 대화는 내용 없이 한 줄만. 비밀 부탁 대화는 위급일 때만 센다 (D55 ③). AI 는 부르지 않는다."""
    _no_ai(monkeypatch)
    room_id = _room(client)
    with SessionLocal() as db:
        _talk(db, room_id, 10, [("요즘 어떠세요?", "사는 게 재미가 없어")], private=private, flag=flag)
        if flag == "NONE":  # 전할 답이 없게 일기 대화로만
            db.query(TalkSession).filter(TalkSession.room_id == room_id).update({"kind": "DIARY"})
        db.commit()
    row = _summarize(room_id)
    assert row.notes == ({"lines": [weekly_ai.CARE_LINE]} if care else None)
    assert (row.qa_list, row.model_version) == ([], "none")


def _pair(n, said, question="그때 어떠셨어요?"):
    return {
        "ref": f"a{n}",
        "question": question,
        "said": said,
        "photo_id": None,
        "date": "2026-11-10",
        "session_id": "s",
        "turn_no": n * 2,
    }


def test_rule_check_drops_only_the_bad_cards():
    pairs = [
        _pair(1, "홍어랑 잡채랑 식혜가 올라갔지"),
        _pair(2, "큰오빠랑 둘이 갔어"),
        _pair(3, "문제를 다 맞혔지"),
        _pair(4, "논에 물 대기 부터 했지"),
        _pair(5, "동네 사람들이 다 모였어"),
    ]
    too_long = "동네 사람들이 " + "아주 " * 20 + "많이 모였대요."
    cards = [
        WeeklyCard(ref="a1", answer="홍어·잡채·식혜를 떠올리셨어요.", quote="홍어랑 잡채랑 식혜"),  # 통과
        WeeklyCard(ref="a9", answer="장에 다녀오셨대요.", quote="장에 다녀왔어"),  # 근거가 된 답이 없다
        WeeklyCard(ref="a2", answer="큰오빠와 갈비찜을 드셨대요.", quote="갈비찜을 먹었어"),  # 하지 않은 말
        WeeklyCard(ref="a3", answer="정답을 다 맞히셨어요.", quote="문제를 다 맞혔지"),  # 금지어
        WeeklyCard(ref="a5", answer="동네 사람들이 다 모였다.", quote="동네 사람들이"),  # 전달형이 아니다
        WeeklyCard(ref="a1", answer="잡채를 떠올리셨어요.", quote="잡채랑 식혜"),  # 같은 답으로 두 장
        WeeklyCard(ref="a5", answer=too_long, quote="동네 사람들이"),  # 60자 넘음
        WeeklyCard(ref="a2", answer="큰오빠랑 가셨대요.", quote="오빠"),  # 구절이 너무 짧다
        WeeklyCard(ref="a4", answer="논에 물 대기부터 하셨대요.", quote="물대기부터 했지"),  # 띄어쓰기만 다르면 통과
    ]
    kept = [(pair["ref"], answer) for pair, answer in weekly_ai.check(cards, pairs)]
    assert kept == [("a1", "홍어·잡채·식혜를 떠올리셨어요."), ("a4", "논에 물 대기부터 하셨대요.")]


def test_at_most_four_cards():
    pairs = [_pair(n, f"{n}번째로 떠오른 이야기예요") for n in range(1, 7)]
    cards = [WeeklyCard(ref=pair["ref"], answer="이야기를 들려주셨어요.", quote="떠오른 이야기") for pair in pairs]
    assert len(weekly_ai.check(cards, pairs)) == WEEKLY_CARDS_MAX


def test_model_gets_only_question_and_answer_pairs(client, monkeypatch):
    """모델에는 질문·답 쌍만 JSON 데이터로 간다 — 비밀 부탁 대화·대화 번호·사진은 가지 않는다."""
    room_id = _room(client)
    with SessionLocal() as db:
        _talk(db, room_id, 10, [("누구랑 가셨어요?", "큰오빠랑 둘이 갔지")])
        _talk(db, room_id, 11, [("요즘 어떠세요?", "애들한테는 말하지 마")], private=True)
        db.commit()
    seen = []

    def fake(prompt_name, data, schema):
        seen.append((prompt_name, data, schema))
        return WeeklyCards(cards=[WeeklyCard(ref="a1", answer="큰오빠와 둘이 가셨대요.", quote="큰오빠랑 둘이")])

    monkeypatch.setattr(llm, "call_json", fake)
    row = _summarize(room_id)
    ((prompt_name, data, schema),) = seen
    assert (prompt_name, schema) == ("weekly_summary", WeeklyCards)
    assert data == {
        "elder_honorific": "할머니",
        "pairs": [{"ref": "a1", "question": "누구랑 가셨어요?", "said": "큰오빠랑 둘이 갔지"}],
    }
    assert "말하지 마" not in json.dumps(data, ensure_ascii=False)
    assert [card["answer"] for card in row.qa_list] == ["큰오빠와 둘이 가셨대요."]


def test_ai_failure_keeps_numbers_and_is_not_called_again(client, monkeypatch):
    """AI 가 실패하면 그 주는 숫자만 — 예외를 내지 않고, 다시 불러도 AI 는 한 번뿐이다."""
    room_id = _room(client)
    with SessionLocal() as db:
        _talk(db, room_id, 10, [("누구랑 가셨어요?", "큰오빠랑 둘이 갔지")])
        db.commit()
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise llm.LlmError("하루 상한")

    monkeypatch.setattr(llm, "call_json", fail)
    row = _summarize(room_id)
    assert (row.qa_list, row.rule_check_passed, row.model_version, row.memory_days) == ([], False, "failed", 1)
    _summarize(room_id)
    assert len(calls) == 1


def test_nested_output_schema_is_strict():
    """카드 목록은 첫 중첩 출력 — 구조화 출력은 $defs 안의 객체에도 additionalProperties: false 를 요구한다."""
    schema = llm._simplify(WeeklyCards.model_json_schema())
    for node in (schema, *schema["$defs"].values()):
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])
        assert "title" not in node
