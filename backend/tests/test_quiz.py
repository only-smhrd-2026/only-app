"""회상 대화 진짜 구현 (AI-01 #12, D42): 4번째 질문 = 문제 은행 문제, 고르는 순서·14일·하루 2개, 슬픔·그만 종료."""

import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.ai import coach, llm, quiz
from app.ai.schemas import CoachTurn
from app.config import ALBUM_TURNS, MAX_TURNS, QUIZ_TURN, ROOT, TZ, now_kst
from app.db import SessionLocal
from app.models import Photo, QuestionBank, TalkSession
from app.routers import sessions
from app.schemas.sessions import AiOut
from tests.conftest import setup_elder

QUESTIONS = json.loads((ROOT / "data" / "question_bank.json").read_text("utf-8"))["questions"]
BANK = [
    QuestionBank(question_id=i + 1, created_by="test", **({"is_active": True} | q)) for i, q in enumerate(QUESTIONS)
]
NONE_POOL = [q for q in BANK if q.is_active and (q.qtype == "COMMON" or (q.qtype == "THEN_NOW" and not q.activity))]
# 순수 함수 테스트는 날짜를 고정한다 — 지금 시각을 쓰면 자정 근처에 기록이 '오늘'로 넘어가 하루 상한에 걸린다
TODAY = date(2026, 11, 10)
NOON_TODAY = datetime(2026, 11, 10, 12, tzinfo=TZ)
CTX = coach.CoachContext(
    "순자", "할머니", None, [{"speaker": "AI", "text": "누구랑 가셨어요?"}, {"speaker": "ELDER", "text": "딸이랑요"}]
)


def yesterday(minutes: int = 0):
    """어제 정오 ± 분 (몇백 분 안쪽이면 늘 어제 날짜)."""
    return NOON_TODAY - timedelta(days=1) + timedelta(minutes=minutes)


# ---------------------------------------------------------------- 고르기 (순수 함수)
def test_order_knowhow_then_remember_then_then_now():
    q1 = quiz.choose(BANK, "김장", "김치 재료", [], TODAY)
    assert q1.qtype == "KNOWHOW" and q1.activity == "김장"
    q2 = quiz.choose(BANK, "김장", "김치 재료", [(q1.code, yesterday())], TODAY)
    assert q2.qtype == "REMEMBER" and q2.category == "김치 재료"  # 김장 활동을 14일 안에 씀 → 노하우 둘 다 빠짐
    q3 = quiz.choose(BANK, "김장", "김치 재료", [(q1.code, yesterday()), (q2.code, yesterday(1))], TODAY)
    assert q3.qtype == "THEN_NOW"


def test_then_now_for_that_activity_comes_before_any_photo_then_now():
    no_market_knowhow = [q for q in BANK if not (q.qtype == "KNOWHOW" and q.activity == "장날")]
    assert quiz.choose(no_market_knowhow, "장날", None, [], TODAY).code == "TN-market-01"


def test_none_photo_rotates_common_pool_then_repeats_oldest():
    history, seen = [], []
    for i in range(len(NONE_POOL)):  # 공통 풀(그때 vs 지금 아무 사진용 + 공통)을 한 번씩 다 낸다
        q = quiz.choose(BANK, None, None, history, TODAY)
        assert q.qtype in ("THEN_NOW", "COMMON") and q.code not in seen
        seen.append(q.code)
        history.append((q.code, yesterday(i)))  # 뒤에 낸 것일수록 최근
    assert quiz.choose(BANK, None, None, history, TODAY).code == seen[0]  # 다 빠짐 → 가장 오래전에 낸 것


def test_daily_cap_two_per_room():
    one = [(NONE_POOL[0].code, NOON_TODAY)]
    assert quiz.choose(BANK, None, None, one, TODAY) is not None
    assert quiz.choose(BANK, None, None, [*one, (NONE_POOL[1].code, NOON_TODAY)], TODAY) is None


def test_inactive_never_chosen():
    tax = json.loads((ROOT / "data" / "taxonomy.json").read_text("utf-8"))
    for a in [None, *tax["activity"]]:
        for c in [None, *tax["category"]]:
            assert quiz.choose(BANK, a, c, [], TODAY).is_active


def test_photo_tags_threshold_none_and_correction():
    assert quiz.photo_tags(None) == (None, None)
    assert quiz.photo_tags(Photo(activity="김장", category="김치 재료")) == (None, None)  # 분류 전
    p = Photo(activity="김장", category="김치 재료", confidence=Decimal("0.69"), analyzed_at=now_kst())
    assert quiz.photo_tags(p) == (None, None)  # 신뢰도 0.7 미만 → none 사진
    p.confidence = Decimal("0.70")
    assert quiz.photo_tags(p) == ("김장", "김치 재료")
    p.activity = "none"
    assert quiz.photo_tags(p) == (None, "김치 재료")
    p.corrected_activity, p.confidence = "장 담그기", Decimal("0.10")  # 가족이 고친 활동은 신뢰도와 상관없이
    assert quiz.photo_tags(p) == ("장 담그기", None)
    p.activity, p.corrected_activity, p.confidence = "김장", "none", Decimal("0.90")  # 'none' 으로 고침도 정정
    assert quiz.photo_tags(p) == (None, "김치 재료")


# ---------------------------------------------------------------- 코치 (모델 출력 검사)
Q_OPEN = quiz.Quiz("KH-test-01", "KNOWHOW", "김장 배추는 몇 포기나 하셨어요?", None)
Q_CHOICE = quiz.Quiz("KH-test-02", "KNOWHOW", "배추는 어떻게 절이셨어요?", ["소금물에", "통소금으로"])


def test_quiz_text_is_bank_original(monkeypatch):
    monkeypatch.setattr(
        llm, "call_json", lambda *a: CoachTurn(text="딸이랑 하셨군요.", suggestions=["많이요", "조금요"])
    )
    reply, signal, _ = coach.next_question(CTX, QUIZ_TURN, Q_OPEN)
    assert reply.text == f"딸이랑 하셨군요. {Q_OPEN.prompt_text}" and signal == "NONE"
    assert reply.suggestions == ["많이요", "조금요"] and reply.question_type == "KNOWHOW"  # 넘기기 칩 없음 (D52 ⑧)

    reply, *_ = coach.next_question(CTX, QUIZ_TURN, Q_CHOICE)  # 2지선다는 선택지가 칩
    assert reply.suggestions == ["소금물에", "통소금으로"]

    monkeypatch.setattr(llm, "call_json", lambda *a: CoachTurn(text="딸이랑 하셨어요?", suggestions=[]))
    reply, *_ = coach.next_question(CTX, QUIZ_TURN, Q_OPEN)  # 맞장구에 질문이 섞임 → 원문만
    assert reply.text == Q_OPEN.prompt_text and reply.suggestions == coach.QUIZ_FALLBACK_CHIPS

    two = CoachTurn(text="딸이랑 하셨군요. 정말 든든하셨겠어요.", suggestions=["네", "네", "다음에 할게요"])
    monkeypatch.setattr(llm, "call_json", lambda *a: two)
    reply, *_ = coach.next_question(CTX, QUIZ_TURN, Q_OPEN)  # 맞장구는 첫 문장만, 칩은 겹침·넘기기를 거름
    assert reply.text == f"딸이랑 하셨군요. {Q_OPEN.prompt_text}"
    assert reply.suggestions == ["네"]

    monkeypatch.setattr(llm, "call_json", lambda *a: CoachTurn(text="네.", suggestions=[coach.SKIP_CHIP]))
    reply, *_ = coach.next_question(CTX, QUIZ_TURN, Q_OPEN)  # 옛 넘기기 칩만 오면 기본 답 칩
    assert reply.suggestions == coach.QUIZ_FALLBACK_CHIPS


def test_llm_failure_still_asks_bank_question(monkeypatch):
    def boom(*a):
        raise llm.LlmError("timeout")

    monkeypatch.setattr(llm, "call_json", boom)
    reply, signal, _ = coach.next_question(CTX, QUIZ_TURN, Q_OPEN)
    assert reply.text == Q_OPEN.prompt_text and reply.question_type == "KNOWHOW" and signal == "NONE"
    assert coach.next_question(CTX, 2) == (coach.FALLBACK_QUESTION, "NONE", False)


def test_signal_rules(monkeypatch):
    monkeypatch.setattr(llm, "call_json", lambda *a: CoachTurn(text="오늘은 여기까지 해요.", signal="STOP"))
    reply, signal, _ = coach.next_question(CTX, 3)
    assert signal == "STOP" and reply.question_type == "CLOSING" and reply.suggestions == []
    first = coach.CoachContext("순자", "할머니")  # 어르신 말 전에는 끝내자는 신호를 무시
    assert coach.next_question(first, 1) == (coach.FALLBACK_QUESTION, "NONE", False)

    skipped = coach.CoachContext(  # 문제에 '다음에 할게요' → 모델이 STOP·SAD 를 내도 대화는 이어 간다
        "순자",
        "할머니",
        None,
        [{"speaker": "AI", "text": "q", "quiz": True}, {"speaker": "ELDER", "text": "다음에 할게요"}],
    )
    for s in ("STOP", "SAD"):
        monkeypatch.setattr(llm, "call_json", lambda *a, s=s: CoachTurn(text="오늘은 여기까지 해요.", signal=s))
        assert coach.next_question(skipped, QUIZ_TURN + 1) == (coach.FALLBACK_QUESTION, "NONE", False)

    def quiz_answer(said):  # 넘기기 칩이 없어져 말로 넘긴다 (D52 ⑧)
        return coach.CoachContext(
            "순자", "할머니", None, [{"speaker": "AI", "text": "q", "quiz": True}, {"speaker": "ELDER", "text": said}]
        )

    monkeypatch.setattr(llm, "call_json", lambda *a: CoachTurn(text="오늘은 여기까지 해요.", signal="STOP"))
    assert coach.next_question(quiz_answer("잘 모르겠어요, 넘어가요"), QUIZ_TURN + 1) == (
        coach.FALLBACK_QUESTION,
        "NONE",
        False,
    )
    assert coach.next_question(quiz_answer("이제 그만할래요"), QUIZ_TURN + 1)[1] == "STOP"  # 진짜 그만은 끝
    monkeypatch.setattr(llm, "call_json", lambda *a: CoachTurn(text="많이 그리우시죠.", signal="SAD"))
    assert coach.next_question(quiz_answer("그때 생각하면 눈물이 나요"), QUIZ_TURN + 1)[1] == "SAD"  # 슬픔은 그대로

    monkeypatch.setattr(llm, "call_json", lambda *a: CoachTurn(text="고마워요. 내일 또 할까요?"))
    assert coach.closing(CTX, MAX_TURNS)[0] == coach.FALLBACK_CLOSING  # 마무리에 질문이 섞임 → 고정 인사


def test_common_is_in_api_contract():
    assert AiOut(text="요즘도 그러세요?", question_type="COMMON").question_type == "COMMON"


# ---------------------------------------------------------------- 세션 API
def _create(client, ctx, kind="MEMORY"):
    body = {"session_id": str(uuid.uuid4()), "kind": kind}
    body |= {"pick_id": ctx["pick"]["pick_id"]} if kind == "MEMORY" else {"photo_id": ctx["photo_ids"][1]}
    r = client.post("/api/elder/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _answer(client, sid, n=1, text="네, 기억나요"):
    for _ in range(n):
        r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": text, "input_type": "CHIP"})
        assert r.status_code == 200, r.text
    return r.json()


def _turns(sid):
    with SessionLocal() as db:
        s = db.get(TalkSession, uuid.UUID(sid))
        return s.turns, s.emotion_flag


def test_fourth_question_is_quiz_recorded_once(client, question_bank, monkeypatch):
    sent = []
    real = llm.call_json
    monkeypatch.setattr(llm, "call_json", lambda name, data, schema: sent.append(data) or real(name, data, schema))
    ctx = setup_elder(client)  # 분류 전 사진 → 공통 풀
    sid = _create(client, ctx)
    r = _answer(client, sid, QUIZ_TURN - 1)
    by_code = {q["code"]: q for q in question_bank}
    asked = [t for t in _turns(sid)[0] if t.get("question_code")]
    assert len(asked) == 1 and asked[0]["speaker"] == "AI"
    q = by_code[asked[0]["question_code"]]
    assert r["turn_no"] == QUIZ_TURN and r["ai"]["question_type"] == q["qtype"] in ("THEN_NOW", "COMMON")
    assert r["ai"]["text"] == f"아, 그러셨군요. {q['prompt_text']}"  # mock 맞장구 + 원문
    assert coach.SKIP_CHIP not in r["ai"]["suggestions"] and len(r["ai"]["suggestions"]) <= 2  # 답 칩만 (D52 ⑧)
    assert sent[QUIZ_TURN - 1]["quiz"]["prompt_text"] == q["prompt_text"]

    r = _answer(client, sid, 1, "다음에 할게요")  # 말로 넘기면 회상으로. 다음 턴 모델은 문제였던 턴을 안다
    assert r["ai"]["question_type"] == "RECALL"
    assert sum(t.get("quiz", False) for t in sent[-1]["turns"]) == 1
    r = _answer(client, sid, MAX_TURNS - QUIZ_TURN)
    assert r["state"] == "ENDED" and r["end_reason"] == "COMPLETED"
    assert sum(bool(t.get("question_code")) for t in _turns(sid)[0]) == 1


def test_classified_photo_knowhow_then_remember_then_daily_cap(client, question_bank):
    ctx = setup_elder(client)
    with SessionLocal() as db:
        for p in db.scalars(select(Photo).where(Photo.room_id == ctx["room_id"])):
            p.activity, p.category, p.confidence, p.analyzed_at = "김장", "김치 재료", Decimal("0.90"), now_kst()
        db.commit()
    types = [_answer(client, _create(client, ctx), QUIZ_TURN - 1)["ai"]["question_type"] for _ in range(3)]
    assert types == ["KNOWHOW", "REMEMBER", "RECALL"]  # 김장 노하우 → 14일 안에 쓴 김장은 빼고 김치 재료 → 오늘 2개 끝


def test_album_has_no_quiz(client, question_bank, monkeypatch):
    ctx = setup_elder(client)
    sid = _create(client, ctx, "ALBUM")
    assert _answer(client, sid, ALBUM_TURNS)["state"] == "ENDED"
    turns, _ = _turns(sid)
    assert not any(t.get("question_code") for t in turns)
    # 사진첩은 2턴에 끝나 4번째 질문(문제 차례)에 닿지 않는다 — 위 검사만으로는
    # '문제는 오늘의 한 장 대화에만'을 못 잡는다. 턴 수를 문제 차례까지 늘려도 사진첩 4번째 질문은 문제가 아니어야 한다
    monkeypatch.setattr(sessions, "ALBUM_TURNS", QUIZ_TURN)
    sid = _create(client, ctx, "ALBUM")
    assert _answer(client, sid, QUIZ_TURN - 1)["ai"]["question_type"] == "RECALL"
    assert not any(t.get("question_code") for t in _turns(sid)[0])


def test_llm_is_told_each_kinds_max_turns(client, monkeypatch):
    """AI 에 넘기는 최대 질문 수(max_turns): 사진첩은 ALBUM_TURNS, 오늘의 한 장은 MAX_TURNS — 질문·마무리 둘 다."""
    sent = []
    real = llm.call_json
    monkeypatch.setattr(llm, "call_json", lambda name, data, schema: sent.append(data) or real(name, data, schema))
    ctx = setup_elder(client)
    _answer(client, _create(client, ctx, "ALBUM"), ALBUM_TURNS)
    questions = [(n, ALBUM_TURNS, False) for n in range(1, ALBUM_TURNS + 1)]
    assert [(d["turn_no"], d["max_turns"], d["closing"]) for d in sent] == [
        *questions,
        (ALBUM_TURNS, ALBUM_TURNS, True),
    ]
    sent.clear()
    _create(client, ctx)
    assert (sent[0]["turn_no"], sent[0]["max_turns"]) == (1, MAX_TURNS)


def test_empty_bank_no_quiz(client):
    ctx = setup_elder(client)
    sid = _create(client, ctx)
    assert _answer(client, sid, QUIZ_TURN - 1)["ai"]["question_type"] == "RECALL"
    assert not any(t.get("question_code") for t in _turns(sid)[0])


def _signal_at(turn_no, signal):
    real = llm.call_json

    def fake(name, data, schema):
        if name == "memory_coach" and not data["closing"] and data["turn_no"] == turn_no:
            return CoachTurn(text="이야기 들려주셔서 고마워요. 오늘은 여기까지 해요.", signal=signal)
        return real(name, data, schema)

    return fake


def test_sad_ends_completed_with_flag(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _signal_at(3, "SAD"))
    ctx = setup_elder(client)
    sid = _create(client, ctx)
    _answer(client, sid)
    r = _answer(client, sid)
    assert r["state"] == "ENDED" and r["end_reason"] == "COMPLETED" and r["turn_no"] == 2
    assert r["ai"]["question_type"] == "CLOSING" and r["ai"]["suggestions"] == []
    assert _turns(sid)[1] == "LOW"  # SAD 는 이제 LOW 로 기록 (D55)
    assert client.get("/api/elder/home").json()["today_pick"]["status"] == "COMPLETED"  # 팝업 다시 안 뜸


def test_stop_ends_user_stop(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _signal_at(2, "STOP"))
    ctx = setup_elder(client)
    sid = _create(client, ctx)
    r = _answer(client, sid, 1, "이제 그만할래")
    assert r["state"] == "ENDED" and r["end_reason"] == "USER_STOP" and _turns(sid)[1] == "NONE"


def test_sad_on_quiz_turn_ends_without_quiz_record(client, question_bank, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _signal_at(QUIZ_TURN, "SAD"))
    ctx = setup_elder(client)
    sid = _create(client, ctx)
    r = _answer(client, sid, QUIZ_TURN - 1)
    assert r["state"] == "ENDED" and r["ai"]["question_type"] == "CLOSING"
    turns, flag = _turns(sid)
    assert flag == "LOW" and not any(t.get("question_code") for t in turns)  # 안 낸 문제는 기록하지 않는다


def test_sad_last_answer_is_flagged_but_completed(client, monkeypatch):
    real = llm.call_json

    def fake(name, data, schema):  # 마무리 인사 때 마지막(8번째) 답이 슬프다고 판단
        if name == "memory_coach" and data["closing"]:
            return CoachTurn(text="이야기 들려주셔서 고마워요.", signal="SAD")
        return real(name, data, schema)

    monkeypatch.setattr(llm, "call_json", fake)
    ctx = setup_elder(client)
    sid = _create(client, ctx)
    r = _answer(client, sid, MAX_TURNS)
    assert r["state"] == "ENDED" and r["end_reason"] == "COMPLETED" and _turns(sid)[1] == "LOW"


def test_model_output_limits():
    """모델이 만드는 말: 한 번에 60자까지, 추천 답변은 빈칸을 빼고 6자 이내 (D52 ④·⑨). 고정 답은 그대로 12자."""
    from pydantic import ValidationError

    from app.ai.schemas import MODEL_TEXT_MAX, CoachReply, DiaryTurn

    assert CoachTurn(text="가" * MODEL_TEXT_MAX, suggestions=["가족 이랑요", "바다요"]).suggestions == [
        "가족 이랑요",
        "바다요",
    ]
    for bad in ({"text": "가" * (MODEL_TEXT_MAX + 1)}, {"text": "네?", "suggestions": ["가족들이랑 갔어요"]}):
        try:
            CoachTurn(**bad)
            raise AssertionError(bad)
        except ValidationError:
            pass
    try:  # 일기 동무도 모델 답이라 6자
        DiaryTurn(text="누구랑 계셨어요?", suggestions=["밖에 다녀왔어요"])
        raise AssertionError("diary chip")
    except ValidationError:
        pass
    assert CoachReply(
        text="오늘은 뭐 하셨어요?", suggestions=["밖에 다녀왔어요"]
    ).suggestions  # 고정 답(코드)은 12자까지


def test_recall_reply_has_two_chips(monkeypatch):
    monkeypatch.setattr(
        llm, "call_json", lambda *a: CoachTurn(text="바다에 가셨군요. 누구랑요?", suggestions=["가족", "친구", "혼자"])
    )
    reply, *_ = coach.next_question(CTX, 2)
    assert reply.suggestions == ["가족", "친구"]  # 늘 2개 (D52 ④)
