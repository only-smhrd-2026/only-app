"""응급 (11/19): 몸이 위급하다는 말(BODY) → 가족에게 바로 + 119 버튼,
가족 홈 긴급 카드([제가 연락했어요]), 30분 뒤 다시 알림.

유료 API 는 부르지 않는다: call_json 을 바꿔 모델 출력을 흉내 낸다.
"""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.ai import coach, llm
from app.ai.schemas import CoachTurn, has_body_words
from app.config import MAX_TURNS, URGENT_REMIND_MIN, URGENT_SHOW_HOURS, now_kst
from app.db import SessionLocal
from app.models import Diary, Notification, TalkSession, UrgentAlert
from app.services import alerts
from tests.conftest import setup_elder, signup
from tests.test_mood_signal import _say, _start


def _body(turn_no=None, closing=False, private=False):
    """그 질문(또는 마무리)을 만들 때 모델이 BODY 를 낸 것처럼."""
    real = llm.call_json

    def fake(name, data, schema):
        if name == "memory_coach" and (data["closing"] if closing else data["turn_no"] == turn_no):
            return CoachTurn(text="많이 아프시군요.", suggestions=[], signal="BODY", private=private)
        return real(name, data, schema)

    return fake


def _urgent_notes(room_id) -> list[str]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(Notification.title)
                .where(Notification.room_id == room_id, Notification.kind == "MOOD_URGENT")
                .order_by(Notification.notification_id)
            )
        )


def _alerts(room_id) -> list[UrgentAlert]:
    with SessionLocal() as db:
        return list(
            db.scalars(select(UrgentAlert).where(UrgentAlert.room_id == room_id).order_by(UrgentAlert.alert_id))
        )


def _age(room_id, minutes) -> None:
    with SessionLocal() as db:
        for alert in db.scalars(select(UrgentAlert).where(UrgentAlert.room_id == room_id)):
            alert.created_at = now_kst() - timedelta(minutes=minutes)
        db.commit()


def test_body_signal_tells_family_and_ends_with_the_119_button(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _body(2, private=True))  # '애들한테 말하지 마'여도 위급은 보낸다
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    out = _say(client, sid, "가슴이 너무 아파서 숨을 못 쉬겠어")
    assert (out["state"], out["end_reason"], out["urgent"]) == ("ENDED", "COMPLETED", "BODY")
    assert out["ai"]["text"] == coach.BODY_CLOSING.text and "119" not in out["ai"]["text"]  # 숫자는 버튼에만
    assert _urgent_notes(ctx["room_id"]) == ["지금 바로 전화해 보세요"]
    [alert] = _alerts(ctx["room_id"])
    assert (alert.kind, str(alert.session_id), alert.acked_at) == ("BODY", sid, None)
    with SessionLocal() as db:
        session = db.get(TalkSession, uuid.UUID(sid))
        assert session.emotion_flag == "NONE"  # 몸 위급은 마음 신호(기운 없는 날)로 세지 않는다
        assert session.turns[-1]["urgent"] == "BODY"
        urgent = Notification.kind == "MOOD_URGENT"
        body = db.scalar(select(Notification.body).where(Notification.room_id == ctx["room_id"], urgent))
        assert "가슴" not in body  # 하신 말은 알림에 넣지 않는다
    # 같은 대화를 다시 열어도(재시도) 119 버튼이 그대로 뜬다
    retry = {"session_id": sid, "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]}
    assert client.post("/api/elder/sessions", json=retry).json()["urgent"] == "BODY"


def test_body_signal_on_the_last_answer(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _body(closing=True))
    ctx = setup_elder(client)
    sid = _start(client, ctx)
    for _ in range(MAX_TURNS - 1):
        assert _say(client, sid)["urgent"] is None
    out = _say(client, sid, "방금 넘어져서 못 일어나겠어")
    assert (out["state"], out["urgent"], out["ai"]["text"]) == ("ENDED", "BODY", coach.BODY_CLOSING.text)
    assert [a.kind for a in _alerts(ctx["room_id"])] == ["BODY"]


def test_family_sees_the_card_and_first_ack_stays(client):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    assert client.get(f"/api/rooms/{room_id}/alert").json() is None
    sid = _start(client, ctx)
    _say(client, sid, "요즘은 정말 죽고 싶어요")  # 위급 낱말 안전망 (D55) — 마음 위급도 같은 카드
    card = client.get(f"/api/rooms/{room_id}/alert").json()
    assert (card["kind"], card["acked_at"], card["acked_by_name"], card["acked_by_me"]) == ("MOOD", None, None, False)
    done = client.post(f"/api/rooms/{room_id}/alerts/{card['alert_id']}/ack")
    assert done.status_code == 200 and done.json()["acked_by_me"] is True
    first = done.json()["acked_at"]
    # 다른 가족에게는 누가 연락했는지 보인다. 뒤에 눌러도 처음 누른 사람 그대로
    token = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"}).json()["url"].split("#", 1)[1]
    signup(client)
    accept = {"token": token, "relation_tag": "GRANDCHILD", "name": "손주"}
    assert client.post("/api/invites/accept", json=accept).status_code == 200
    seen = client.get(f"/api/rooms/{room_id}/alert").json()
    assert (seen["acked_by_name"], seen["acked_by_me"], seen["acked_at"]) == ("테스터", False, first)
    late = client.post(f"/api/rooms/{room_id}/alerts/{card['alert_id']}/ack").json()
    assert (late["acked_by_name"], late["acked_by_me"], late["acked_at"]) == ("테스터", False, first)
    # 남의 가족방은 있는지도 모르게 404
    signup(client)
    assert client.get(f"/api/rooms/{room_id}/alert").status_code == 404
    assert client.post(f"/api/rooms/{room_id}/alerts/{card['alert_id']}/ack").status_code == 404


def test_unknown_alert_is_404_and_old_card_goes_away(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _body(2))
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    _say(client, _start(client, ctx), "숨이 차서 못 견디겠어")
    alert_id = _alerts(room_id)[0].alert_id
    assert client.post(f"/api/rooms/{room_id}/alerts/{alert_id + 999}/ack").status_code == 404
    _age(room_id, URGENT_SHOW_HOURS * 60 + 1)
    assert client.get(f"/api/rooms/{room_id}/alert").json() is None  # 하루가 지나면 카드를 내린다


def test_unacked_alert_is_told_once_more_after_30_minutes(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _body(2))
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    _say(client, _start(client, ctx), "숨이 차서 못 견디겠어")
    with SessionLocal() as db:
        assert alerts.remind(db) == 0  # 아직 30분 전
    _age(room_id, URGENT_REMIND_MIN + 1)
    with SessionLocal() as db:
        assert alerts.remind(db) == 1
        assert alerts.remind(db) == 0  # 알림마다 한 번만
    assert _urgent_notes(room_id) == ["지금 바로 전화해 보세요", "아직 연락한 가족이 없어요"]


def test_acked_or_stale_alert_is_not_told_again(client, monkeypatch):
    monkeypatch.setattr(llm, "call_json", _body(2))
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    _say(client, _start(client, ctx), "숨이 차서 못 견디겠어")
    with SessionLocal() as db:  # 같은 방에 열린 알림이 하나 더 — [제가 연락했어요] 한 번에 같이 닫힌다
        db.add(UrgentAlert(room_id=room_id, kind="MOOD"))
        db.commit()
    newest = client.get(f"/api/rooms/{room_id}/alert").json()
    assert client.post(f"/api/rooms/{room_id}/alerts/{newest['alert_id']}/ack").status_code == 200
    assert all(a.acked_at is not None for a in _alerts(room_id))
    _age(room_id, URGENT_REMIND_MIN + 1)
    with SessionLocal() as db:
        assert alerts.remind(db) == 0
        stale = now_kst() - timedelta(hours=URGENT_SHOW_HOURS + 1)
        db.add(UrgentAlert(room_id=room_id, kind="BODY", created_at=stale))
        db.commit()
        assert alerts.remind(db) == 0  # 하루 넘은 것은 다시 알리지 않는다
    assert len(_urgent_notes(room_id)) == 1  # 처음 알림 하나뿐


def test_body_words():
    for said in (
        "방금 넘어져서 못 일어나겠어",
        "숨을 못 쉬겠어",
        "어지러워서 쓰러질 것 같아",
        "다리에 힘이 없어서 일어날 수가 없어",
        "피가 안 멈춰",
        "119 불러 줘",
        "구급차 좀 불러 줘",
        "숨 못 쉬겠어",  # 조사가 빠진 말 (11/19 보강)
        "숨을 못 쉬어",
        "숨 안 쉬어져",
        "피를 토해",
        "119 좀 불러 줘",
        "일일구 불러 줘",  # 음성 인식이 숫자를 한글로 적을 때
        "일일구 좀 불러",
    ):
        assert has_body_words(said), said
    # 늘 있는 불편·옛이야기·마음이 아프다는 말은 낱말로 잡지 않는다 (회상 대화의 AI 가 맥락으로 본다)
    for said in (
        "계단 오르면 숨이 차",
        "요즘 허리가 아파",
        "그때 넘어져서 다리를 다쳤지",
        "그 생각만 하면 가슴이 아파",
        "그때는 가슴이 너무 아팠지",
        "어지러워서 쓰러질 것 같았어",
        "피가 안 멈췄던 적이 있어",
        "아이고 살려줘 웃겨 죽겠네",
        "어제는 일찍 못 일어났어",
        "작년에 넘어져서 못 일어났어",  # 지난 일은 잡지 않는다 (11/19)
        "젊을 때 피를 토한 적이 있어",
        "그때 숨을 못 쉬었어",
    ):
        assert not has_body_words(said), said


def test_body_words_close_a_diary_talk_without_ai_and_save_no_diary(client, monkeypatch):
    def boom(name, data, schema):  # AI 가 실패해도 낱말 안전망은 돈다
        raise llm.LlmError("시간 초과")

    monkeypatch.setattr(llm, "call_json", boom)
    ctx = setup_elder(client)
    sid = _start(client, ctx, kind="DIARY")
    out = _say(client, sid, "방금 넘어져서 못 일어나겠어")
    assert (out["state"], out["end_reason"], out["urgent"]) == ("ENDED", "USER_STOP", "BODY")
    assert out["ai"]["text"] == coach.BODY_CLOSING.text
    assert [a.kind for a in _alerts(ctx["room_id"])] == ["BODY"]
    with SessionLocal() as db:  # 위급한 말이 그대로 일기가 되지 않는다
        assert db.scalar(select(Diary.diary_id).where(Diary.room_id == ctx["room_id"])) is None


def test_repeated_urgent_words_do_not_flood_the_family(client):
    """대화를 새로 열어 가며 위급한 말을 되풀이해도, 확인 안 된 같은 알림이 있는 30분 동안은 새로 알리지 않는다."""
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    for _ in range(3):
        out = _say(client, _start(client, ctx, kind="DIARY"), "방금 넘어져서 못 일어나겠어")
        assert (out["state"], out["urgent"]) == ("ENDED", "BODY")  # 대화 마무리와 119 버튼은 매번 그대로
    assert len(_alerts(room_id)) == 1 and len(_urgent_notes(room_id)) == 1
    _say(client, _start(client, ctx, kind="DIARY"), "요즘은 정말 죽고 싶어요")  # 다른 종류(마음 위급)는 따로 알린다
    assert [a.kind for a in _alerts(room_id)] == ["BODY", "MOOD"]
    newest = client.get(f"/api/rooms/{room_id}/alert").json()
    assert client.post(f"/api/rooms/{room_id}/alerts/{newest['alert_id']}/ack").status_code == 200
    _say(
        client, _start(client, ctx, kind="DIARY"), "방금 넘어져서 못 일어나겠어"
    )  # 가족이 확인한 뒤의 새 위급은 다시 알린다
    assert [a.kind for a in _alerts(room_id)] == ["BODY", "MOOD", "BODY"]
