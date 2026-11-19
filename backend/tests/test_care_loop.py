"""돌봄 루프 (11/18 멘토링): 어제 들은 것 → 판단(코드) → 오늘 첫인사 안부 → 어르신 답 → 가족 돌봄 일지.

유료 API 는 부르지 않는다: mock 이거나 call_json 을 바꿔 모델 출력을 흉내 낸다.
"""

import uuid
from datetime import datetime, time, timedelta

from sqlalchemy import select

from app.ai import coach, llm
from app.ai import weekly as weekly_ai
from app.ai.schemas import CoachTurn
from app.config import CARE_ASK_MAX, TZ, now_kst, today_kst
from app.db import SessionLocal
from app.models import CareDay, Diary, MoodCheck, TalkSession
from app.services import care
from tests.conftest import setup_elder
from tests.test_mood_signal import _say, _start

SLEEP = "요즘 잠을 통 못 자"


def _talk(room_id, days_ago, said=SLEEP, *, low=True, private=False, words=None) -> uuid.UUID:
    """그날 회상 대화 하나: 질문 → 어르신 말 → (기운 없는 말이면 표시가 붙은) 다음 질문."""
    said = " ".join(["말"] * words) if words else said
    turns = [
        {"turn_no": 1, "speaker": "AI", "text": "이 사진 보니 어떠세요?"},
        {"turn_no": 2, "speaker": "ELDER", "text": said, "input_type": "VOICE", "reply_to_turn_no": 1},
        {"turn_no": 3, "speaker": "AI", "text": "그러셨군요. 누구랑 가셨어요?"} | ({"signal": "LOW"} if low else {}),
    ]
    sid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(
            TalkSession(
                session_id=sid,
                room_id=room_id,
                kind="MEMORY",
                input_mode="VOICE",
                started_at=datetime.combine(today_kst() - timedelta(days=days_ago), time(10), tzinfo=TZ),
                emotion_flag="LOW" if low else "NONE",
                private_flag=private,
                turns=turns,
            )
        )
        db.commit()
    return sid


def _row(room_id, day=None) -> CareDay | None:
    with SessionLocal() as db:
        return db.scalar(select(CareDay).where(CareDay.room_id == room_id, CareDay.care_date == (day or today_kst())))


def _plan(room_id, days_ahead=0) -> CareDay:
    with SessionLocal() as db:
        row = care.plan(db, room_id, today_kst() + timedelta(days=days_ahead))
        db.commit()
        db.refresh(row)
        return row


def _answer_signal(signal):
    """오늘의 안부에 하신 답을 보고(= 그다음 질문을 만들 때) 모델이 signal 을 낸 것처럼."""
    real = llm.call_json

    def fake(name, data, schema):
        if name == "memory_coach" and data["turn_no"] == 1 and not data["closing"]:
            return CoachTurn(text="그러셨군요. 이 사진 보니 어떠세요?", suggestions=["좋아요", "글쎄요"], signal=signal)
        return real(name, data, schema)

    return fake


def test_topics_from_words_and_mood_check():
    assert care.talk_topic("요즘 잠을 통 못 자") == "SLEEP"
    assert care.talk_topic("입맛이 없어서 죽만 먹어") == "APPETITE"
    assert care.talk_topic("혼자 있으니 적적해") == "LONELY"
    assert care.talk_topic("다 귀찮아") == "ENERGY"
    assert care.talk_topic("몰라 그냥 그래") == "MOOD"
    assert care.talk_topic("잠깐 나갔다 왔어") == "MOOD"  # '잠깐'은 잠 이야기가 아니다
    # 높게 답한 문항부터. '며칠'(1)은 안부로 삼지 않고, 자책·집중·느려짐 문항(6~8번)은 쓰지 않는다
    assert care.check_topics([1, 2, 3, 0, 2, 3, 3, 3]) == ["SLEEP", "MOOD", "APPETITE"]
    assert care.check_say([0, 0, 3, 0, 2, 0, 0, 0]).startswith("잠이 편치 않은 날이 많으셨군요.")
    assert care.check_say([1, 1, 1, 1, 1, 1, 1, 1]) is None


def test_loop_heard_asked_answered_and_family_journal(client, monkeypatch):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    _talk(room_id, 1)  # 어제: "요즘 잠을 통 못 자" (AI 가 기운 없는 말로 봄)
    sent = []
    real = llm.call_json

    def spy(name, data, schema):
        sent.append((name, data))
        return real(name, data, schema)

    monkeypatch.setattr(llm, "call_json", spy)
    out = client.post(
        "/api/elder/sessions",
        json={"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]},
    ).json()
    # 실행: 오늘 첫 질문이 그 안부 — 지난 이야기 질문과 같은 AI 에 '들은 말' 한 문장을 준다
    # (어르신 말 원문은 주지 않는다)
    name, data = sent[0]
    assert (name, data["fact"], data["when"]) == ("story_question", "잠을 잘 못 주무신다고 하셨어요.", "어제")
    row = _row(room_id)
    assert (row.level, row.reasons, row.source, row.topic) == ("WATCH", ["LOW_TALK"], "TALK", "SLEEP")
    assert row.asked_at is not None and row.reaction is None
    assert row.numbers["talks"] == 1 and row.numbers["low"] is True
    with SessionLocal() as db:
        first = db.get(TalkSession, uuid.UUID(out["session_id"])).turns[0]
    assert first["care"] == "SLEEP" and "fact_id" not in first
    # 가족 돌봄 일지: 들은 것 · 한 일. 아직 답 전
    day = client.get(f"/api/rooms/{room_id}/care").json()["days"][0]
    assert (day["level"], day["heard"], day["did"], day["reaction"]) == (
        "WATCH",
        "잠을 잘 못 주무신다고 하셨어요.",
        "첫인사로 잠 안부를 여쭸어요.",
        None,
    )
    # 반응: 괜찮다고 하시면(신호 없음) 그 안부는 닫는다 — 내일도 모레도 다시 묻지 않는다
    _say(client, out["session_id"], "응 어제는 잘 잤어")
    assert _row(room_id).reaction == "OK"
    assert client.get(f"/api/rooms/{room_id}/care").json()["days"][0]["reaction"] == "괜찮다고 하셨어요."
    assert _plan(room_id, 1).topic is None and _plan(room_id, 2).topic is None
    # 그 답은 사진 이야기가 아니라 주간 이야기 카드 후보에 넣지 않는다
    with SessionLocal() as db:
        session = db.get(TalkSession, uuid.UUID(out["session_id"]))
        assert all(pair["said"] != "응 어제는 잘 잤어" for pair in weekly_ai.pairs_of([session]))


def test_still_bad_is_asked_again_after_a_rest_and_not_forever(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _answer_signal("LOW"))
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    _talk(room_id, 1)
    sid = _start(client, ctx)
    _say(client, sid, "아니 또 못 잤어")
    assert _row(room_id).reaction == "SAME"
    day = client.get(f"/api/rooms/{room_id}/care").json()["days"][0]
    assert day["reaction"] == "아직 편치 않다고 하셨어요. 전화 한 통 드려 보세요."
    # 내일은 쉬고(어제 여쭌 안부), 모레 다시 — 들은 날은 처음 그날 그대로
    assert _plan(room_id, 1).topic is None
    again = _plan(room_id, 2)
    assert (again.source, again.topic, again.heard_on) == ("TALK", "SLEEP", today_kst() - timedelta(days=1))
    # 같은 안부는 CARE_ASK_MAX 번까지만
    with SessionLocal() as db:
        for n in range(CARE_ASK_MAX):
            row = db.scalar(
                select(CareDay).where(CareDay.room_id == room_id, CareDay.care_date == today_kst() + timedelta(days=n))
            )
            row.topic, row.source, row.asked_at, row.reaction = "SLEEP", "TALK", now_kst(), "SAME"
        db.commit()
    late = _plan(room_id, CARE_ASK_MAX + 2)
    assert late.topic is None and "SAME_AGAIN" in late.reasons and late.level == "CARE"


def test_denied_care_question_is_dropped(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _answer_signal("DENY"))
    ctx = setup_elder(client)
    _talk(ctx["room_id"], 1)
    sid = _start(client, ctx)
    out = _say(client, sid, "내가 언제 그랬어")
    assert out["state"] == "CONTINUE"  # 대화는 이어 간다
    assert _row(ctx["room_id"]).reaction == "DENY"
    assert _plan(ctx["room_id"], 2).topic is None
    day = client.get(f"/api/rooms/{ctx['room_id']}/care").json()["days"][0]
    assert day["reaction"] == "그런 적 없다고 하셔서 더 여쭙지 않아요."


def test_ai_failure_keeps_the_care_question_for_later(client, monkeypatch):
    def boom(name, data, schema):
        raise llm.LlmError("시간 초과")

    monkeypatch.setattr(llm, "call_json", boom)
    ctx = setup_elder(client)
    _talk(ctx["room_id"], 1)
    out = client.post(
        "/api/elder/sessions",
        json={"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]},
    ).json()
    assert out["ai"]["text"] == coach.FALLBACK_QUESTION.text
    row = _row(ctx["room_id"])
    assert row.topic == "SLEEP" and row.asked_at is None  # 못 여쭘 — 오늘 다음 대화에서 다시 시도
    with SessionLocal() as db:
        assert "care" not in db.get(TalkSession, uuid.UUID(out["session_id"])).turns[0]
    day = client.get(f"/api/rooms/{ctx['room_id']}/care").json()["days"][0]
    assert day["did"] == "오늘 첫인사로 잠 안부를 여쭐게요."


def test_ai_failure_on_the_answer_is_not_written_down_as_fine(client, monkeypatch):
    """안부에 하신 답을 AI 가 읽지 못한 턴(실패)은 '괜찮다고 하셨어요'로 적지 않는다 — 가족이 잘못 안심하지 않게."""
    ctx = setup_elder(client)
    _talk(ctx["room_id"], 1)
    sid = _start(client, ctx)  # 첫 질문(잠 안부)은 AI 가 정상으로 만든다
    assert _row(ctx["room_id"]).asked_at is not None

    def boom(name, data, schema):
        raise llm.LlmError("시간 초과")

    monkeypatch.setattr(llm, "call_json", boom)
    out = _say(client, sid, "아직도 통 못 자")
    # 대화는 고정 질문으로 이어 간다. 돌봄 일지의 '답'은 빈 채로 둔다
    assert out["state"] == "CONTINUE" and out["ai"]["text"] == coach.FALLBACK_QUESTION.text
    assert _row(ctx["room_id"]).reaction is None
    assert client.get(f"/api/rooms/{ctx['room_id']}/care").json()["days"][0]["reaction"] is None


def test_private_talk_is_not_used(client):
    ctx = setup_elder(client)
    _talk(ctx["room_id"], 1, private=True)
    row = _plan(ctx["room_id"])
    assert (row.level, row.topic, row.numbers["low"], row.numbers["turns"]) == ("USUAL", None, False, 0)
    assert client.get(f"/api/rooms/{ctx['room_id']}/care").json()["days"] == []


def test_diary_mood_and_mood_check_items_become_questions(client):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    with SessionLocal() as db:
        db.add(
            MoodCheck(
                room_id=room_id,
                check_date=today_kst() - timedelta(days=3),
                answers=[0, 0, 3, 0, 2, 0, 0, 0],
                total=5,
                level="DOWN",
            )
        )
        db.commit()
    first = _plan(room_id)  # 새로 들은 말·일기가 없으면 마음 체크에서 가장 높게 답한 문항
    assert (first.source, first.topic, first.heard_on) == ("CHECK", "SLEEP", today_kst() - timedelta(days=3))
    assert (first.level, first.reasons) == ("WATCH", ["CHECK_ITEM"])
    with SessionLocal() as db:
        db.get(CareDay, first.care_id).asked_at = now_kst()
        db.add(
            Diary(
                room_id=room_id,
                author_type="ELDER",
                body="혼자 있었다.",
                mood="LONELY",
                illustration_type="NONE",
                request_id=uuid.uuid4(),
                status="POSTED",
                posted_at=now_kst(),
            )
        )
        db.commit()
    second = _plan(room_id, 1)  # 어제 일기의 기분이 먼저
    assert (second.source, second.topic, second.reasons) == ("DIARY", "LONELY", ["DIARY_MOOD"])
    third = _plan(room_id, 2)  # 그다음 마음 체크 문항 — 이미 여쭌 잠은 건너뛴다
    assert (third.source, third.topic) == ("CHECK", "APPETITE")


def test_levels_from_numbers(client):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    for days_ago in range(2, 8):  # 평소: 한마디 10어절쯤
        _talk(room_id, days_ago, low=False, words=10)
    _talk(room_id, 1, low=False, words=3)  # 어제는 3어절
    row = _plan(room_id)
    assert (row.level, row.reasons, row.topic) == ("WATCH", ["TALK_DOWN"], None)
    assert row.numbers["avg_words"] == 3
    quiet = _plan(room_id, 1)  # 내일 기준: 오늘은 이야기도 일기도 없음 — 평소 거의 매일 하시던 분
    assert (quiet.level, quiet.reasons) == ("WATCH", ["QUIET"])
    day = client.get(f"/api/rooms/{room_id}/care").json()["days"][0]
    assert (day["heard"], day["did"], day["notes"]) == (None, None, ["말수가 평소보다 줄었어요."])


def test_two_low_days_out_of_three_is_care(client):
    ctx = setup_elder(client)
    _talk(ctx["room_id"], 1)
    _talk(ctx["room_id"], 3)
    assert _plan(ctx["room_id"]).level == "CARE"


def test_mood_check_thanks_names_the_item_in_plain_words(client):
    setup_elder(client)
    said = client.post("/api/elder/mood-check", json={"answers": [0, 0, 0, 0, 3, 0, 0, 0]}).json()
    assert said["ok"] is True and said["say"].startswith("입맛이 없는 날이 많으셨군요.")
    assert not any(word in said["say"] for word in ("점", "단계", "우울"))
