"""외부 상태 확인에 DB 연결 성공 여부도 포함한다."""

import pytest

from app.deps import get_db
from app.main import app


def test_health_checks_database(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True and response.json()["db"] is True
    assert {"env", "time"} <= response.json().keys()


def test_llm_fail_streak_counts_real_failures_and_resets(client, monkeypatch):
    """AI 가 연달아 실패하면 /api/health 에 보인다 — 고정 문장으로 돌아 멀쩡해 보이는 장애를 알아채게 (11/26)."""
    from app.ai import llm
    from app.ai.schemas import ElderReply
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "_fail_streak", 0)
    monkeypatch.setattr(llm, "daily_allowed", lambda *a: True)

    def api_error(*a):
        raise llm.LlmError("RateLimitError")

    monkeypatch.setattr(llm, "_anthropic", api_error)
    for _ in range(2):
        with pytest.raises(llm.LlmError):
            llm.call_json("elder_reply", {"said": "고맙다"}, ElderReply)
    assert client.get("/api/health").json()["llm_fail_streak"] == 2

    def refused(*a):
        raise llm.LlmRefused("refusal")  # 모델은 답했다 — 장애로 세지 않는다

    monkeypatch.setattr(llm, "_anthropic", refused)
    with pytest.raises(llm.LlmRefused):
        llm.call_json("elder_reply", {"said": "고맙다"}, ElderReply)
    assert llm.fail_streak() == 2
    monkeypatch.setattr(llm, "_anthropic", lambda *a: (ElderReply(text="고맙다"), 10))
    llm.call_json("elder_reply", {"said": "고맙다"}, ElderReply)
    assert client.get("/api/health").json()["llm_fail_streak"] == 0


def test_health_database_failure_is_503(client):
    class BrokenDB:
        def execute(self, statement):
            raise ConnectionError("test database unavailable")

    def broken_db():
        yield BrokenDB()

    app.dependency_overrides[get_db] = broken_db
    try:
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.json() == {"ok": False, "db": False}
    finally:
        app.dependency_overrides.pop(get_db, None)
