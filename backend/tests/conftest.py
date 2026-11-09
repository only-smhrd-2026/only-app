"""테스트는 docker 의 Postgres 에 `only_app_test` DB 를 만들어 db/schema.sql 을 적용한다 (schema.sql 이 원천, D1).

사전 조건: `docker compose up -d db` (저장소 루트). 실행: backend 폴더에서 `uv run pytest`.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text

TEST_DB = "only_app_test"
_dotenv = dotenv_values(Path(__file__).resolve().parents[2] / ".env")  # 저장소 루트 .env (DB 포트 등)
_base = (
    os.environ.get("DATABASE_URL")
    or _dotenv.get("DATABASE_URL")
    or "postgresql+psycopg://only:only@127.0.0.1:5432/only_app"
)
_server = _base.rsplit("/", 1)[0]
os.environ["DATABASE_URL"] = f"{_server}/{TEST_DB}"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["APP_ENV"] = "dev"
os.environ["UPLOAD_DIR"] = os.path.join(os.path.dirname(__file__), ".uploads")
os.environ["STORAGE"] = "local"  # .env 가 r2 여도 테스트 파일은 tests/.uploads 에만
for _p in ("LLM_PROVIDER", "STT_PROVIDER", "TTS_PROVIDER", "IMAGE_PROVIDER"):
    os.environ[_p] = "mock"  # .env 에 실제 키가 있어도 테스트는 유료 API 를 부르지 않는다

_admin = create_engine(f"{_server}/postgres", isolation_level="AUTOCOMMIT")
with _admin.connect() as c:
    if not c.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}).first():
        c.execute(text(f'CREATE DATABASE "{TEST_DB}"'))

from fastapi.testclient import TestClient  # noqa: E402  (환경 변수 설정 뒤에 import)

from app.config import ROOT  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import FamilyRoom, Photo  # noqa: E402
from app.services import storage  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema():
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        conn.exec_driver_sql((ROOT / "db" / "schema.sql").read_text("utf-8"))
    yield


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def signup(client: TestClient, email: str | None = None) -> dict:
    email = email or f"{uuid.uuid4().hex[:8]}@test.local"
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "test1234", "name": "테스터", "terms_agreed": True},
    )
    assert r.status_code == 201, r.text
    return r.json()["user"] | {"email": email}


def make_room(client: TestClient) -> dict:
    r = client.post("/api/rooms", json={"elder_name": "순자", "elder_honorific": "할머니", "relation_tag": "CHILD"})
    assert r.status_code == 201, r.text
    return r.json()


def add_photos(room_id: int, n: int = 3) -> list[int]:
    batch = uuid.uuid4()
    ids = []
    with SessionLocal() as db:
        for i in range(n):
            key = f"rooms/{room_id}/{batch}/{i}.jpg"
            storage.put(key, b"\xff\xd8\xff\xd9")  # 최소 JPEG 마커
            p = Photo(room_id=room_id, upload_batch_id=batch, object_key=key, source="FAMILY", caption=f"사진 {i}")
            db.add(p)
            db.flush()
            ids.append(p.photo_id)
        room = db.get(FamilyRoom, room_id)
        room.memory_time = __import__("datetime").time(0, 0)  # 테스트는 시각과 무관하게 오늘의 한 장이 뽑히게
        db.commit()
    return ids


def connect_device(client: TestClient, room_id: int) -> dict:
    r = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "ELDER_DEVICE"})
    assert r.status_code == 201, r.text
    token = r.json()["url"].split("#", 1)[1]
    r = client.post("/api/devices/connect", json={"token": token})
    assert r.status_code == 200, r.text
    return r.json()


def setup_elder(client: TestClient) -> dict:
    """가족 가입 → 가족방 → 사진 3장 → 기기 연결 → 홈. 반환: room_id, photo_ids, pick."""
    signup(client)
    room = make_room(client)
    photo_ids = add_photos(room["room_id"])
    connect_device(client, room["room_id"])
    home = client.get("/api/elder/home")
    assert home.status_code == 200, home.text
    return {"room_id": room["room_id"], "photo_ids": photo_ids, "pick": home.json()["today_pick"]}
