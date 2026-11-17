"""슬픔·거부·무응답 뒤에는 문제 기록 없이 끝낸다 (시나리오 3, FR-AI-005)."""

import uuid

import pytest

from app.ai import llm
from app.ai.schemas import CoachTurn
from app.db import SessionLocal
from app.models import TalkSession
from tests.conftest import setup_elder
from tests.test_session_stub import _create


@pytest.mark.parametrize("case,reason", [("sad", "COMPLETED"), ("stop", "USER_STOP"), ("quiet", "NO_RESPONSE")])
def test_hard_day_ends_without_quiz(client, question_bank, monkeypatch, case, reason):
    ctx = setup_elder(client)
    sid = _create(client, ctx)["session_id"]
    real = llm.call_json

    def answer(name, data, schema):
        if name == "memory_coach" and case != "quiet":
            return CoachTurn(text="오늘은 여기까지 하고 편히 쉬세요.", signal="SAD" if case == "sad" else "STOP")
        return real(name, data, schema)

    monkeypatch.setattr(llm, "call_json", answer)
    body = {"text": "오늘 마음이 슬퍼요" if case == "sad" else "그만할래", "input_type": "CHIP"}
    if case == "quiet":
        body = {"input_type": "BUTTON", "event": "NO_RESPONSE"}
    for _ in range(3 if case == "quiet" else 1):
        response = client.post(f"/api/elder/sessions/{sid}/turns", json=body)
        assert response.status_code == 200
    assert response.json()["state"] == "ENDED" and response.json()["end_reason"] == reason
    with SessionLocal() as db:
        session = db.get(TalkSession, uuid.UUID(sid))
        assert session.ended_at is not None
        assert not any(t.get("question_code") for t in session.turns)
    assert client.get(f"/api/elder/sessions/{sid}").json()["state"] == "ENDED"
