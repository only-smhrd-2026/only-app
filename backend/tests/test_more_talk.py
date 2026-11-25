"""11/25 실사용: 마지막 답에 '더 얘기할래'가 있으면 끊지 않고 질문을 더 한다(회상·일기). 기분 묻기는 늘 마지막."""

import uuid

import pytest

from app.ai import coach
from app.config import DIARY_TURNS, MAX_TURNS, MORE_TURNS
from tests.conftest import setup_elder
from tests.test_diary import MOODS


@pytest.mark.parametrize(
    "text,want",
    [
        ("좀 더 이야기하고 싶은데", True),
        ("할머니가 조금 더 얘기할 수 있을까", True),
        ("아직 할 말 있어", True),
        ("얘기 좀 더 하자", True),
        ("끊지 마", True),
        ("바다에 갔었지", False),
        ("더 맛있었어", False),
        ("그만할래", False),
    ],
)
def test_wants_more(text, want):
    assert coach.wants_more(text) is want


def _turn(client, sid, text):
    return client.post(f"/api/elder/sessions/{sid}/turns", json={"text": text, "input_type": "CHIP"}).json()


def test_diary_more_then_mood_last(client):
    setup_elder(client)
    sid = str(uuid.uuid4())
    assert client.post("/api/elder/sessions", json={"session_id": sid, "kind": "DIARY"}).status_code == 201
    for a in ("경로당에 다녀왔어요", "영자 씨랑요", "경로당에서요"):
        _turn(client, sid, a)
    r = _turn(client, sid, "아직 할 말이 더 있어")  # 기분 묻기 앞 답 → 기분을 묻지 않고 더 묻는다
    assert r["turn_no"] == DIARY_TURNS and r["ai"]["suggestions"] != MOODS
    for _ in range(MORE_TURNS - 1):
        r = _turn(client, sid, "시장도 갔어요")
    r = _turn(client, sid, "그게 다예요")
    assert r["ai"]["suggestions"] == MOODS and r["turn_no"] == DIARY_TURNS + MORE_TURNS  # 기분은 늘 마지막
    r = _turn(client, sid, "더 얘기할래")  # 한 번만 늘린다 — 다시 말하면 마무리
    assert r["state"] == "ENDED" and r["end_reason"] == "COMPLETED" and "?" not in r["ai"]["text"]


def test_memory_more_once(client):
    ctx = setup_elder(client)
    sid = str(uuid.uuid4())
    body = {"session_id": sid, "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]}
    assert client.post("/api/elder/sessions", json=body).status_code == 201
    for _ in range(MAX_TURNS - 1):
        r = _turn(client, sid, "바다요")
    r = _turn(client, sid, "좀 더 얘기하고 싶어")
    assert r["state"] != "ENDED" and r["turn_no"] == MAX_TURNS + 1
