"""외부 상태 확인에 DB 연결 성공 여부도 포함한다."""

from app.deps import get_db
from app.main import app


def test_health_checks_database(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True and response.json()["db"] is True
    assert {"env", "time"} <= response.json().keys()


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
