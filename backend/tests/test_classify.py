"""사진 분류 AI-04 (D71): 무엇을·언제 분류하나, 실패하면, 하루 상한, 대화 재료(보이는 모습 한 줄), 문제 고르기까지."""

import base64
import io
import json
import uuid
from types import SimpleNamespace

import anthropic
import pytest
from PIL import Image
from sqlalchemy import update

from app import security
from app.ai import classify, coach, llm
from app.ai.schemas import PhotoLabel
from app.config import CLASSIFY_PER_DAY, CLASSIFY_SYNC_SEC, QUIZ_TURN, now_kst, settings, today_kst
from app.db import SessionLocal
from app.models import FamilyRoom, Photo, TalkSession
from app.routers import sessions
from app.services import storage
from tests.conftest import setup_elder

REAL_CALL = llm.call_json
KIMJANG = PhotoLabel(
    scene="마당에서 여러 사람이 배추를 절이는 모습",
    usable=True,
    is_old=False,
    season="WINTER",
    activity="김장",
    category="김치 재료",
    confidence=0.9,
)


def jpeg(side: tuple[int, int] = (1600, 1200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", side, "skyblue").save(buf, "JPEG")
    return buf.getvalue()


def real_files(photo_ids: list[int]) -> None:
    """add_photos 는 최소 JPEG 마커만 넣는다 — 분류하려면 열리는 사진이 필요하다."""
    with SessionLocal() as db:
        for pid in photo_ids:
            storage.put(db.get(Photo, pid).object_key, jpeg())


def only_these_pending(photo_ids: list[int]) -> None:
    """테스트끼리 DB 를 비우지 않으므로, 앞 테스트가 남긴 분류 전 사진은 분류 끝으로 돌려 둔다."""
    with SessionLocal() as db:
        db.execute(
            update(Photo)
            .where(Photo.analyzed_at.is_(None), Photo.photo_id.not_in(photo_ids))
            .values(analyzed_at=now_kst())
        )
        db.commit()


@pytest.fixture
def vision(monkeypatch):
    """분류 실호출 흉내: 'anthropic' 으로 두고 call_json 을 바꾼다. 답(또는 예외)을 차례로 돌려준다."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")

    def use(*replies):
        left, calls = list(replies), []

        def fake(name, data, schema, **kw):
            calls.append((name, data, kw))
            r = left.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        monkeypatch.setattr(llm, "call_json", fake)
        return calls

    return use


def test_job_classifies_unclassified_family_photos_only(client, vision):
    ctx = setup_elder(client)
    family = ctx["photo_ids"]
    real_files(family)
    with SessionLocal() as db:  # 분류하지 않는 사진: 가족 일기·어르신 카메라(대화 열 때만)·지운 사진
        others = [
            Photo(
                room_id=ctx["room_id"],
                upload_batch_id=uuid.uuid4(),
                object_key=f"rooms/{ctx['room_id']}/other/{i}.jpg",
                source=source,
                status=status,
            )
            for i, (source, status) in enumerate(
                [("FAMILY_DIARY", "ACTIVE"), ("ELDER_CAMERA", "ACTIVE"), ("FAMILY", "DELETED")]
            )
        ]
        db.add_all(others)
        db.commit()
        other_ids = [p.photo_id for p in others]
    only_these_pending(family + other_ids)
    calls = vision(KIMJANG, KIMJANG, KIMJANG)
    with SessionLocal() as db:
        assert classify.run_pending(db) == (3, 0)
        assert classify.run_pending(db) == (0, 0)  # 다 분류함 — 다시 부르지 않는다
        p = db.get(Photo, family[0])
        assert (p.activity, p.category, p.season, p.is_old, p.usable) == ("김장", "김치 재료", "WINTER", False, True)
        assert float(p.confidence) == 0.9 and p.ai_scene == KIMJANG.scene and p.analyzed_at is not None
        assert p.model_version == f"{settings.LLM_MODEL}/{classify.PROMPT_VERSION}"
        assert all(db.get(Photo, i).analyzed_at is None for i in other_ids)
    assert [name for name, *_ in calls] == ["classify_photo"] * 3
    sent = Image.open(io.BytesIO(calls[0][2]["image"]))
    assert sent.format == "JPEG" and max(sent.size) == 1024  # 저장본보다 작게 줄여 보낸다


def test_refused_or_broken_is_done_but_outage_waits(client, vision):
    ctx = setup_elder(client)
    ids = ctx["photo_ids"]
    real_files(ids[:2])  # 셋째는 add_photos 의 최소 마커뿐 — 열 수 없는 파일
    only_these_pending(ids)
    calls = vision(llm.LlmRefused("refusal"), llm.LlmError("APITimeoutError"))
    with SessionLocal() as db:
        # 거절 → 분류 끝(none), 시간 초과 → 분류 전 그대로, 열 수 없는 파일 → 부르지 않고 분류 끝
        assert classify.run_pending(db) == (2, 1)
        refused, later, broken = (db.get(Photo, i) for i in ids)
        assert (refused.activity, refused.category, float(refused.confidence)) == ("none", "none", 0.0)
        assert refused.usable is None and refused.ai_scene is None  # 오늘의 한 장에서 빼지 않는다
        assert later.analyzed_at is None
        assert broken.analyzed_at is not None and broken.activity == "none"
    assert len(calls) == 2

    # 장애가 이어지면 이번 차례는 2번 실패에서 멈춘다 — 사진마다 시간 상한까지 기다리지 않게
    more = setup_elder(client)["photo_ids"]
    real_files(more)
    only_these_pending([ids[1], *more])
    calls = vision(llm.LlmError("APIConnectionError"), llm.LlmError("APIConnectionError"))
    with SessionLocal() as db:
        assert classify.run_pending(db) == (0, 4)
    assert len(calls) == 2


def test_mock_never_calls_vision(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("mock 에서는 부르지 않는다")

    monkeypatch.setattr(llm, "call_json", boom)
    ctx = setup_elder(client)
    with SessionLocal() as db:
        assert classify.run_pending(db) == (0, 0)
        assert classify.classify(db.get(Photo, ctx["photo_ids"][0])) is False


class FakeClaude:
    def __init__(self, *replies: str):
        self.replies, self.calls, self.messages = list(replies), [], self

    def create(self, **kw):
        self.calls.append(kw)
        text = SimpleNamespace(type="text", text=self.replies.pop(0))
        usage = SimpleNamespace(input_tokens=1, output_tokens=1)
        return SimpleNamespace(usage=usage, stop_reason="end_turn", content=[text])


def test_vision_request_and_own_daily_cap(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(security._daily_hits, ("classify", today_kst()), 0)
    monkeypatch.setitem(security._daily_hits, ("llm", today_kst()), 0)
    answer = {
        "scene": "가" * 80,
        "usable": True,
        "is_old": True,
        "season": "SPRING",
        "activity": "우주여행",  # 목록 밖 → none
        "category": "봄꽃",
        "confidence": 1.7,
    }
    fake = FakeClaude(json.dumps(answer, ensure_ascii=False))
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: fake)
    image = jpeg((40, 30))
    label = llm.call_json("classify_photo", {}, PhotoLabel, image=image, timeout=CLASSIFY_SYNC_SEC)
    assert (label.activity, label.category, label.confidence, len(label.scene)) == ("none", "봄꽃", 1.0, 60)
    kw = fake.calls[0]
    picture, data = kw["messages"][0]["content"]
    assert picture["type"] == "image" and picture["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(picture["source"]["data"]) == image and data == {"type": "text", "text": "{}"}
    assert "# 분류 기준" in kw["system"] and "활동 목록: 김장" in kw["system"]  # taxonomy.json 한 곳의 기준
    assert kw["timeout"] == CLASSIFY_SYNC_SEC
    assert "none" in kw["output_config"]["format"]["schema"]["properties"]["activity"]["enum"]
    # 분류는 대화와 따로 센다 (D71)
    assert security._daily_hits[("classify", today_kst())] == 1 and security._daily_hits[("llm", today_kst())] == 0
    security._daily_hits[("classify", today_kst())] = CLASSIFY_PER_DAY
    with pytest.raises(llm.LlmError) as e:
        llm.call_json("classify_photo", {}, PhotoLabel, image=image)
    assert not isinstance(e.value, llm.LlmRefused) and len(fake.calls) == 1  # 상한은 '다음에 다시'
    assert PhotoLabel(**(answer | {"scene": "점수 매기는 모습"})).scene == ""  # 대화 재료라 금지어가 섞이면 버린다


def test_diary_classifies_camera_photo_before_first_question(client, monkeypatch):
    setup_elder(client)
    sent = []
    old = KIMJANG.model_copy(
        update={"is_old": True, "activity": "none", "category": "none", "scene": "바닷가에서 찍은 흑백 사진"}
    )

    def fake(name, data, schema, **kw):
        sent.append((name, data, kw))
        if name == "classify_photo":
            return old
        raise llm.LlmError("no key")  # 일기 질문은 고정 문장으로

    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "call_json", fake)

    def camera() -> int:
        r = client.post("/api/elder/photos", files={"files": ("a.jpg", jpeg(), "image/jpeg")})
        assert r.status_code == 201, r.text
        return r.json()["photo_id"]

    def diary(photo_id: int) -> str:
        body = {"session_id": str(uuid.uuid4()), "kind": "DIARY", "photo_id": photo_id}
        r = client.post("/api/elder/sessions", json=body)
        assert r.status_code == 201, r.text
        return r.json()["ai"]["text"]

    photo_id = camera()
    assert "옛날 사진 같네요" in diary(photo_id)  # 분류가 첫 질문 전에 붙어 옛 사진 일기 (D58)
    assert [n for n, *_ in sent] == ["classify_photo", "diary_buddy"]
    assert sent[0][2]["timeout"] == CLASSIFY_SYNC_SEC and sent[1][1]["scene"] == old.scene  # 1번 질문 재료 (D71)
    diary(photo_id)  # 같은 사진으로 다시 일기를 열면 다시 분류하지 않는다
    assert [n for n, *_ in sent].count("classify_photo") == 1

    outage = []

    def slow(name, *a, **k):  # 분류가 늦거나 실패하면 평소 일기로 바로 연다
        outage.append(name)
        raise llm.LlmError("APITimeoutError")

    monkeypatch.setattr(llm, "call_json", slow)
    photo_id = camera()
    assert "오늘은 뭐 하셨어요?" in diary(photo_id) and outage[0] == "classify_photo"
    with SessionLocal() as db:
        assert db.get(Photo, photo_id).analyzed_at is None


def test_scene_is_question_material_only(client, monkeypatch):
    sent = {}

    def fake(name, data, schema, **kw):
        sent[name] = data
        raise llm.LlmError("stop")

    monkeypatch.setattr(llm, "call_json", fake)
    ctx = coach.CoachContext("순자", "할머니", None, [{"speaker": "ELDER", "text": "바다 갔어"}], scene="바닷가 모습")
    coach.next_question(ctx, 2)
    coach.diary_question(ctx, 1)
    coach.diary_draft(ctx)
    assert sent["memory_coach"]["scene"] == sent["diary_buddy"]["scene"] == "바닷가 모습"
    assert "바닷가 모습" not in json.dumps(sent["diary_draft"], ensure_ascii=False)  # 초안은 어르신 말만 (D36)

    room_ctx = setup_elder(client)
    with SessionLocal() as db:
        photo = db.get(Photo, room_ctx["photo_ids"][0])
        photo.ai_scene = "글자 많은 화면 캡처"
        room = db.get(FamilyRoom, room_ctx["room_id"])
        talk = TalkSession(kind="MEMORY", photo_id=photo.photo_id, turns=[])
        assert sessions.coach_context(db, room, talk).scene == "글자 많은 화면 캡처"
        photo.usable = False  # 대화에 못 쓰는 사진이면 재료로 넘기지 않는다
        assert sessions.coach_context(db, room, talk).scene is None
        db.rollback()


def test_kimjang_photo_gets_kimjang_knowhow_end_to_end(client, question_bank, vision, monkeypatch):
    """AI-05 끝 기준 '김장 사진이면 김장 노하우 질문' — 분류(예약 작업) → 오늘의 한 장 → 4번째 질문."""
    ctx = setup_elder(client)
    real_files(ctx["photo_ids"])
    only_these_pending(ctx["photo_ids"])
    vision(KIMJANG, KIMJANG, KIMJANG)
    with SessionLocal() as db:
        assert classify.run_pending(db) == (3, 0)
    sent = []  # 이제 코치는 mock — 생각 문제 틀을 못 지켜 은행 원문으로 간다
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    monkeypatch.setattr(llm, "call_json", lambda name, data, schema: sent.append(data) or REAL_CALL(name, data, schema))
    sid = str(uuid.uuid4())
    body = {"session_id": sid, "kind": "MEMORY", "pick_id": ctx["pick"]["pick_id"]}
    r = client.post("/api/elder/sessions", json=body)
    assert r.status_code == 201, r.text
    for _ in range(QUIZ_TURN - 1):
        r = client.post(f"/api/elder/sessions/{sid}/turns", json={"text": "네, 기억나요", "input_type": "CHIP"})
    assert r.json()["ai"]["question_type"] == "KNOWHOW"
    assert sent[0]["scene"] == KIMJANG.scene  # 첫 질문부터 사진 한 줄을 받는다
    assert sent[QUIZ_TURN - 1]["quiz"]["example"].startswith("김장")  # 모델에 주는 예시도 김장 노하우
    with SessionLocal() as db:
        turns = db.get(TalkSession, uuid.UUID(sid)).turns
    assert [t["question_code"] for t in turns if t.get("question_code")][0].startswith("KH-kimjang-")


def test_photo_list_shows_ai_label_and_family_fix(client, vision):
    """가족방 탭 '올린 사진'(D73): 목록에 AI 가 본 활동·모습, 가족이 고친 활동은 다음 대화 데이터로."""
    ctx = setup_elder(client)
    room, first = ctx["room_id"], ctx["photo_ids"][0]
    real_files(ctx["photo_ids"])
    only_these_pending(ctx["photo_ids"])

    def listed() -> dict:
        r = client.get(f"/api/rooms/{room}/photos")
        assert r.status_code == 200, r.text
        return {p["photo_id"]: p for p in r.json()["photos"]}

    before = listed()[first]
    assert (before["source"], before["analyzed"], before["ai_activity"], before["ai_scene"]) == (
        "FAMILY",
        False,
        None,
        None,
    )
    vision(KIMJANG, KIMJANG, KIMJANG)
    with SessionLocal() as db:
        assert classify.run_pending(db) == (3, 0)
    after = listed()[first]
    assert (after["analyzed"], after["ai_activity"], after["ai_scene"]) == (True, "김장", KIMJANG.scene)
    assert after["corrected_activity"] is None

    r = client.patch(f"/api/rooms/{room}/photos/{first}/correction", json={"corrected_activity": "장 담그기"})
    assert r.status_code == 200, r.text
    assert (r.json()["corrected_activity"], r.json()["ai_activity"]) == (
        "장 담그기",
        "김장",
    )  # AI 가 본 것은 그대로 둔다
    with SessionLocal() as db:
        talk = TalkSession(kind="MEMORY", photo_id=first, turns=[])
        assert sessions.coach_context(db, db.get(FamilyRoom, room), talk).photo["activity"] == "장 담그기"
    client.patch(f"/api/rooms/{room}/photos/{first}/correction", json={"corrected_activity": "none"})
    with SessionLocal() as db:
        talk = TalkSession(kind="MEMORY", photo_id=first, turns=[])
        assert sessions.coach_context(db, db.get(FamilyRoom, room), talk).photo["activity"] is None  # 맞는 것 없음
