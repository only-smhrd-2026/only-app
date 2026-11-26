"""이야기 기억 AI-07 (#46, D77) — 어제 대화에서 기억 뽑기, 고르기, 그날 첫 회상 대화의 첫 질문,
'그런 말 안 했어', 주간 이야기에서 빼기.

유료 API 는 부르지 않는다: mock 이거나 call_json 을 바꿔 모델 출력을 흉내 낸다.
"""

import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.ai import coach, llm, story
from app.ai import weekly as weekly_ai
from app.ai.schemas import CoachTurn, StoryFactItem, StoryFactItems
from app.config import MAX_TURNS, QUIZ_TURN, TZ, now_kst, today_kst
from app.db import SessionLocal
from app.models import StoryFact, TalkSession, WeeklySummary
from app.services import weekly
from tests.conftest import make_room, setup_elder, signup

PLAN = "내일은 경로당 가서 화투 칠 거야"
EVENT = "마당에 국화 심었지"


def _room(client) -> int:
    signup(client)
    return make_room(client)["room_id"]


def _talk(room_id, day, qa, *, private=False, flag="NONE", confidence=0.9, story_turn=False) -> uuid.UUID:
    """AI 질문 → 어르신 답을 번갈아 넣은 그날 대화 하나. story_turn 이면 첫 AI 턴이 어제 이야기 질문(fact_id)."""
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
    if story_turn:
        turns[0]["fact_id"] = 1
    sid = uuid.uuid4()
    with SessionLocal() as db:
        db.add(
            TalkSession(
                session_id=sid,
                room_id=room_id,
                kind="MEMORY",
                input_mode="VOICE",
                started_at=datetime.combine(day, time(10), tzinfo=TZ),
                private_flag=private,
                emotion_flag=flag,
                turns=turns,
            )
        )
        db.commit()
    return sid


def _fact(room_id, session_id, day, *, kind="PLAN", turn_no=2, active=True) -> int:
    with SessionLocal() as db:
        fact = StoryFact(
            room_id=room_id,
            session_id=session_id,
            source_turn_no=turn_no,
            fact_text="경로당에 가신다고 하셨어요.",
            kind=kind,
            fact_date=day,
            is_active=active,
            expires_at=datetime.combine(day + timedelta(days=30), time(0), tzinfo=TZ),
        )
        db.add(fact)
        db.commit()
        return fact.fact_id


def _start(client, pick_id) -> dict:
    body = {"session_id": str(uuid.uuid4()), "kind": "MEMORY", "pick_id": pick_id}
    r = client.post("/api/elder/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _say(client, sid, text="잘 다녀왔어요") -> dict:
    r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": text, "input_type": "CHIP"})
    assert r.status_code == 200, r.text
    return r.json()


def _turns(sid) -> list[dict]:
    with SessionLocal() as db:
        return db.get(TalkSession, uuid.UUID(sid)).turns


def test_check_keeps_only_what_the_elder_said():
    pairs = [
        {"ref": "a1", "question": "내일은 뭐 하세요?", "said": PLAN},
        {"ref": "a2", "question": "오늘은요?", "said": EVENT},
    ]
    items = [
        StoryFactItem(ref="a1", kind="PLAN", fact="경로당에 가신다고 하셨어요.", quote="경로당 가서"),
        StoryFactItem(ref="a1", kind="EVENT", fact="화투를 치신대요.", quote="화투 칠 거야"),  # 같은 답에서 두 번째
        StoryFactItem(ref="a2", kind="EVENT", fact="장미를 심으셨대요.", quote="장미 심었지"),  # 하지 않은 말
        StoryFactItem(ref="a2", kind="EVENT", fact="국화를 심으셨다", quote="국화 심었지"),  # '요'로 끝나지 않음
        StoryFactItem(ref="a2", kind="EVENT", fact="국화 테스트를 하셨대요.", quote="국화 심었지"),  # 금지어
        StoryFactItem(ref="a9", kind="EVENT", fact="없는 답이에요.", quote="마당에 국화"),  # 없는 답
        StoryFactItem(ref="a2", kind="EVENT", fact="마당에 국화를 심으셨대요.", quote="마당에국화"),  # 빈칸 무시
    ]
    kept = story.check(items, pairs)
    assert [(pair["ref"], item.kind, fact) for pair, item, fact in kept] == [
        ("a1", "PLAN", "경로당에 가신다고 하셨어요."),
        ("a2", "EVENT", "마당에 국화를 심으셨대요."),
    ]


def test_extract_saves_quoted_facts_from_plain_talks_once(client, monkeypatch):
    room_id = _room(client)
    day = today_kst() - timedelta(days=1)
    plain = _talk(room_id, day, [("내일은 뭐 하세요?", PLAN), ("오늘은 뭐 하셨어요?", EVENT)])
    _talk(room_id, day, [("누구랑 가셨어요?", "애들한테는 말하지 마, 병원 다녀왔어")], private=True)
    _talk(room_id, day, [("요즘 어떠세요?", "입맛이 없어서 죽만 먹었어")], flag="LOW")
    _talk(room_id, day, [("뭐 사셨어요?", "시장에서 고등어 샀어")], confidence=0.5)
    _talk(room_id, day - timedelta(days=1), [("그저께는요?", "그저께 이야기는 안 들어가요")])
    _talk(room_id, day, [("어제 경로당 가신다고 하셨죠?", "응 잘 다녀왔어 재밌더라")], story_turn=True)
    sent = []

    def fake(name, data, schema):
        sent.append((name, data))
        ref = {pair["said"]: pair["ref"] for pair in data["pairs"]}
        return StoryFactItems(
            facts=[
                StoryFactItem(ref=ref[PLAN], kind="PLAN", fact="경로당에 가신다고 하셨어요.", quote="경로당 가서"),
                StoryFactItem(ref=ref[EVENT], kind="EVENT", fact="마당에 국화를 심으셨대요.", quote="국화 심었지"),
            ]
        )

    monkeypatch.setattr(llm, "call_json", fake)
    with SessionLocal() as db:
        assert story.extract(db, room_id, day) == 2
        assert story.extract(db, room_id, day) == 0  # 작업이 다시 돌아도 AI 를 부르지 않는다
        facts = db.scalars(select(StoryFact).where(StoryFact.room_id == room_id).order_by(StoryFact.fact_id)).all()
    assert len(sent) == 1 and sent[0][0] == "story_facts"
    # 비밀 부탁·기운 없음·잘못 들었을 수 있는 답·다른 날·어제 이야기에 한 답은 AI 에 가지 않는다
    assert [pair["said"] for pair in sent[0][1]["pairs"]] == [PLAN, EVENT]
    assert [(f.session_id, f.source_turn_no, f.kind, f.fact_date, f.is_active, f.used_at) for f in facts] == [
        (plain, 2, "PLAN", day, True, None),
        (plain, 4, "EVENT", day, True, None),
    ]
    assert facts[0].expires_at == datetime.combine(day + timedelta(days=30), time(0), tzinfo=TZ)


def test_extract_ai_failure_saves_nothing(client, monkeypatch):
    room_id = _room(client)
    day = today_kst() - timedelta(days=1)
    _talk(room_id, day, [("내일은 뭐 하세요?", PLAN)])

    def boom(*args, **kwargs):
        raise llm.LlmError("장애")

    monkeypatch.setattr(llm, "call_json", boom)
    with SessionLocal() as db:
        assert story.extract(db, room_id, day) == 0
        assert db.scalar(select(StoryFact.fact_id).where(StoryFact.room_id == room_id)) is None


def test_run_removes_expired_and_keeps_going_when_a_room_fails(client, monkeypatch):
    day = date(2020, 1, 1)  # 다른 테스트의 대화가 없는 날
    rooms = [_room(client), _room(client)]
    for room_id in rooms:
        _talk(room_id, day, [("오늘은요?", EVENT)])
    expired = _fact(rooms[0], _talk(rooms[0], day, [("예전에는요?", PLAN)]), day)  # 보관 기간(30일)이 지났다
    calls = []

    def flaky(db, room_id, d):
        calls.append(room_id)
        if room_id == rooms[0]:
            raise RuntimeError("방 하나 실패")
        return 1

    monkeypatch.setattr(story, "extract", flaky)
    with SessionLocal() as db:
        assert story.run(db, day) == (2, 1)
        assert db.get(StoryFact, expired) is None
    assert sorted(calls) == sorted(rooms)


def test_pick_most_recent_day_plan_first_once_a_day(client):
    room_id = _room(client)
    today = today_kst()
    sid = _talk(room_id, today - timedelta(days=1), [("오늘은요?", EVENT)])
    with SessionLocal() as db:
        assert story.pick(db, room_id) is None  # 기억이 없다
    _fact(room_id, sid, today - timedelta(days=8))  # 7일보다 오래됨
    with SessionLocal() as db:
        assert story.pick(db, room_id) is None
    older = _fact(room_id, sid, today - timedelta(days=3), kind="EVENT")
    event = _fact(room_id, sid, today - timedelta(days=2), kind="EVENT")
    plan = _fact(room_id, sid, today - timedelta(days=2), kind="PLAN")
    with SessionLocal() as db:
        assert story.pick(db, room_id).fact_id == plan  # 가장 최근 날, 할 일 먼저
        db.get(StoryFact, plan).used_at = now_kst() - timedelta(days=1)  # 어제 물었다
        db.commit()
        assert story.pick(db, room_id).fact_id == event  # 물은 기억은 다시 묻지 않는다
        db.get(StoryFact, event).used_at = now_kst()  # 오늘 물었다
        db.commit()
        assert story.pick(db, room_id) is None  # 하루 한 번
        db.get(StoryFact, event).used_at = now_kst() - timedelta(days=1)
        db.commit()
        assert story.pick(db, room_id) is None  # 가장 최근 날 기억을 다 물었으면 더 앞날로 가지 않는다
        db.get(StoryFact, plan).is_active = False
        db.get(StoryFact, event).is_active = False
        db.commit()
        assert story.pick(db, room_id).fact_id == older  # 꺼진 기억만 남은 날은 건너뛴다
    assert story.when(today - timedelta(days=1)) == "어제"
    assert story.when(today - timedelta(days=2)) == "그저께"
    assert story.when(today - timedelta(days=5)) == "며칠 전"


def test_first_memory_talk_starts_with_story(client, monkeypatch, question_bank):
    ctx = setup_elder(client)
    room_id, pick_id = ctx["room_id"], ctx["pick"]["pick_id"]
    yesterday = today_kst() - timedelta(days=1)
    fact_id = _fact(room_id, _talk(room_id, yesterday, [("내일은 뭐 하세요?", PLAN)]), yesterday)
    seen = []
    real = llm.call_json

    def spy(name, data, schema):
        if name == "memory_coach":  # 코치가 본 사진 질문 번호·최대 수·문제·마무리
            seen.append((data["turn_no"], data["max_turns"], bool(data.get("quiz")), data["closing"]))
        return real(name, data, schema)

    monkeypatch.setattr(llm, "call_json", spy)
    first = _start(client, pick_id)
    sid = first["session_id"]
    assert first["ai"]["text"].startswith("할머니, 어제 ") and first["turn_no"] == 1  # mock 이 쓴 어제 이야기 질문
    assert _turns(sid)[0]["fact_id"] == fact_id
    with SessionLocal() as db:
        assert db.get(StoryFact, fact_id).used_at is not None
    for _ in range(MAX_TURNS):  # 어제 이야기 질문도 MAX_TURNS 안에 든다 (D79)
        out = _say(client, sid)
    assert out["state"] == "ENDED" and out["end_reason"] == "COMPLETED"
    # 코치는 사진 질문 번호 1~(MAX_TURNS-1)로 본다. 문제는 끝에서 두 번째(QUIZ_TURN — 어제 이야기도 세는 순번)
    photo = [(n, MAX_TURNS - 1, n == QUIZ_TURN - 1, False) for n in range(1, MAX_TURNS)]
    assert seen == [*photo, (MAX_TURNS - 1, MAX_TURNS - 1, False, True)]
    with SessionLocal() as db:
        assert db.get(TalkSession, uuid.UUID(sid)).turn_count == MAX_TURNS
    again = _start(client, pick_id)  # 같은 날 다시 연 회상 대화는 묻지 않는다 (하루 한 번)
    assert "fact_id" not in _turns(again["session_id"])[0]


def test_story_ai_failure_starts_with_fixed_question(client, monkeypatch):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    yesterday = today_kst() - timedelta(days=1)
    fact_id = _fact(room_id, _talk(room_id, yesterday, [("내일은 뭐 하세요?", PLAN)]), yesterday)
    called = []

    def timeout(name, data, schema):
        called.append(name)
        raise llm.LlmError("APITimeoutError")

    monkeypatch.setattr(llm, "call_json", timeout)
    first = _start(client, ctx["pick"]["pick_id"])
    assert first["ai"]["text"] == coach.FALLBACK_QUESTION.text
    assert called == ["story_question"]  # AI 를 한 번 더 기다리지 않는다 (화면 15초)
    assert "fact_id" not in _turns(first["session_id"])[0]  # 평소 대화 — 질문 번호도 그대로
    with SessionLocal() as db:
        assert db.get(StoryFact, fact_id).used_at is None  # 묻지 못한 기억은 남는다


def test_deny_turns_the_fact_off_and_talk_goes_on(client, monkeypatch):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    yesterday = today_kst() - timedelta(days=1)
    fact_id = _fact(room_id, _talk(room_id, yesterday, [("내일은 뭐 하세요?", PLAN)]), yesterday)
    real = llm.call_json

    def fake(name, data, schema):
        if name == "memory_coach" and not data["closing"] and data["turns"][0].get("story"):
            text = "제가 잘못 알았나 봐요. 이 사진 보니 어떠세요?"
            return CoachTurn(text=text, suggestions=["좋아요", "글쎄요"], signal="DENY")
        return real(name, data, schema)

    monkeypatch.setattr(llm, "call_json", fake)
    sid = _start(client, ctx["pick"]["pick_id"])["session_id"]
    out = _say(client, sid, "내가 언제 그런 말을 했어")
    assert out["state"] == "CONTINUE" and out["ai"]["text"].startswith("제가 잘못 알았나 봐요")
    out = _say(client, sid, "좋아요")  # 어제 이야기 다음이 아닌 답의 DENY 는 아무것도 끄지 않고 대화도 이어 간다
    assert out["state"] == "CONTINUE"
    with SessionLocal() as db:
        assert db.get(StoryFact, fact_id).is_active is False
        assert db.get(TalkSession, uuid.UUID(sid)).emotion_flag == "NONE"


def test_weekly_skips_story_answers_and_denied_facts(client):
    room_id = _room(client)
    day = date(2026, 11, 12)  # 11/9 주 (11/8 19:00 ~ 11/15 19:00)
    qa = [("이 사진 보니 어떠세요?", "우리 큰딸 시집가던 날이야"), ("뭐 드셨어요?", "잔치국수를 먹었지")]
    talk = _talk(room_id, day, qa)
    _talk(room_id, day, [("어제 경로당 가신다고 하셨죠?", "응 잘 다녀왔어 재밌더라")], story_turn=True)
    _fact(room_id, talk, day, turn_no=4, active=False)  # 잔치국수 답이 근거인 기억 — 어르신이 '그런 말 안 했어'
    with SessionLocal() as db:
        weekly.build(db, room_id, datetime(2026, 11, 15, 19, tzinfo=TZ))
        weekly_ai.summarize(db, room_id, date(2026, 11, 9))
        row = db.scalar(select(WeeklySummary).where(WeeklySummary.room_id == room_id))
    assert [card["answer"] for card in row.qa_list] == ["'우리 큰딸 시집가던 날이야'라고 하셨어요."]


LIKE = "나는 된장찌개가 제일 맛있어"


def _add(room_id, session_id, day, text, kind, *, keep_days=30, used=False) -> None:
    with SessionLocal() as db:
        db.add(
            StoryFact(
                room_id=room_id,
                session_id=session_id,
                source_turn_no=2,
                fact_text=text,
                kind=kind,
                fact_date=day,
                used_at=now_kst() if used else None,
                expires_at=datetime.combine(day + timedelta(days=keep_days), time(0), tzinfo=TZ),
            )
        )
        db.commit()


def test_check_keeps_likes_apart_from_asks():
    """좋아하시는 것(PREFERENCE)은 안부 기억 3개와 따로 2개까지 (11/26)."""
    pairs = [{"ref": f"a{i}", "question": "뭐 좋아하세요?", "said": f"{i}번 노래 좋아해 {LIKE}"} for i in range(6)]
    items = [StoryFactItem(ref=f"a{i}", kind="EVENT", fact="노래하셨대요.", quote="노래 좋아해") for i in range(3)]
    items += [
        StoryFactItem(ref=f"a{i}", kind="PREFERENCE", fact="된장찌개를 좋아하신대요.", quote="된장찌개가")
        for i in (3, 4, 5)
    ]
    kinds = [item.kind for _, item, _ in story.check(items, pairs)]
    assert kinds == ["EVENT"] * 3 + ["PREFERENCE"] * 2


def test_extract_keeps_likes_90_days(client, monkeypatch):
    room_id = _room(client)
    day = today_kst() - timedelta(days=1)
    _talk(room_id, day, [("뭐 좋아하세요?", LIKE), ("내일은요?", PLAN)])

    def fake(name, data, schema):
        ref = {pair["said"]: pair["ref"] for pair in data["pairs"]}
        return StoryFactItems(
            facts=[
                StoryFactItem(ref=ref[LIKE], kind="PREFERENCE", fact="된장찌개를 좋아하신대요.", quote="된장찌개가"),
                StoryFactItem(ref=ref[PLAN], kind="PLAN", fact="경로당에 가신다고 하셨어요.", quote="경로당 가서"),
            ]
        )

    monkeypatch.setattr(llm, "call_json", fake)
    with SessionLocal() as db:
        assert story.extract(db, room_id, day) == 2
        rows = {f.kind: f.expires_at for f in db.scalars(select(StoryFact).where(StoryFact.room_id == room_id))}
        assert rows["PREFERENCE"] == datetime.combine(day + timedelta(days=90), time(0), tzinfo=TZ)
        assert rows["PLAN"] == datetime.combine(day + timedelta(days=30), time(0), tzinfo=TZ)
        assert story.pick(db, room_id).kind == "PLAN"  # 좋아하시는 것은 안부로 묻지 않는다
        assert story.likes(db, room_id) == ["된장찌개를 좋아하신대요."]


def test_heard_skips_asked_and_likes_dedupe(client):
    room_id = _room(client)
    today = today_kst()
    sid = _talk(room_id, today - timedelta(days=1), [("뭐 하세요?", PLAN)])
    _add(room_id, sid, today - timedelta(days=1), "경로당에 가신다고 하셨어요.", "PLAN", used=True)
    _add(room_id, sid, today - timedelta(days=2), "마당에 국화를 심으셨대요.", "EVENT")
    _add(room_id, sid, today - timedelta(days=9), "열흘 전 이야기예요.", "EVENT")  # 7일 밖
    _add(room_id, sid, today - timedelta(days=1), "된장찌개를 좋아하신대요.", "PREFERENCE", keep_days=90)
    _add(room_id, sid, today - timedelta(days=40), "된장찌개를 좋아하신대요.", "PREFERENCE", keep_days=90)  # 같은 문장
    _add(room_id, sid, today - timedelta(days=100), "지난 것이에요.", "PREFERENCE", keep_days=90)  # 기간 지남
    with SessionLocal() as db:
        assert [f["text"] for f in story.heard(db, room_id)] == [
            "경로당에 가신다고 하셨어요.",
            "마당에 국화를 심으셨대요.",
        ]
        assert story.heard(db, room_id, unasked=True) == [{"heard_on": "그저께", "text": "마당에 국화를 심으셨대요."}]
        assert story.likes(db, room_id) == ["된장찌개를 좋아하신대요."]


def test_diary_and_chat_get_heard_and_likes(client, monkeypatch):
    """일기·잡담 AI 데이터에 지난 이야기·좋아하시는 것이 들어간다 (11/26)."""
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    yday = today_kst() - timedelta(days=1)
    sid = _talk(room_id, yday, [("내일은요?", PLAN)])
    _add(room_id, sid, yday, "경로당에 가신다고 하셨어요.", "PLAN")
    _add(room_id, sid, yday, "된장찌개를 좋아하신대요.", "PREFERENCE", keep_days=90)
    seen: dict[str, dict] = {}
    real = llm.call_json

    def spy(name, data, schema, **kw):
        seen.setdefault(name, data)
        return real(name, data, schema, **kw)

    monkeypatch.setattr(llm, "call_json", spy)
    for kind in ("DIARY", "CHAT"):
        r = client.post("/api/elder/sessions", json={"session_id": str(uuid.uuid4()), "kind": kind})
        assert r.status_code == 201, r.text
    for name in ("diary_buddy", "chat_buddy"):
        assert seen[name]["facts"] == [{"heard_on": "어제", "text": "경로당에 가신다고 하셨어요."}], name
        assert seen[name]["likes"] == ["된장찌개를 좋아하신대요."], name
