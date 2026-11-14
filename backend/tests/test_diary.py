"""일기·그림일기 흐름 (D36) — 질문 3개 → 초안(그림까지 기다림) → '네, 올려요' 1회 게시·가족 알림 → 가족 '새 일기'."""

import base64
import io
import uuid
from datetime import timedelta

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select

from app.ai import coach, image, llm, tts
from app.ai.schemas import BANNED_WORDS, CoachReply, DiaryDraft
from app.config import DIARY_DRAFT_MIN, settings
from app.db import SessionLocal
from app.models import Diary, Notification, Photo
from app.routers import diaries, sessions
from tests.conftest import add_photos, connect_device, make_room, setup_elder, signup

JPEG_SOI = b"\xff\xd8"
MOODS = ["맑음", "구름", "비", "달"]


def _family_and_elder(client) -> int:
    """가족 가입 → 가족방(사진 3장) → 기기 연결. 같은 client 에 가족·기기 쿠키가 둘 다 있다. 일기는 사진 없이 쓴다."""
    return setup_elder(client)["room_id"]


def _talk(client, answers=("경로당에 다녀왔어요", "영자 씨랑요", "맑음"), photo_id=None) -> tuple[str, list[dict]]:
    body = {"session_id": str(uuid.uuid4()), "kind": "DIARY"} | ({"photo_id": photo_id} if photo_id else {})
    r = client.post("/api/elder/sessions", json=body)
    assert r.status_code == 201, r.text
    sid, replies = r.json()["session_id"], [r.json()]
    for a in answers:
        replies.append(client.post(f"/api/elder/sessions/{sid}/turns", json={"text": a, "input_type": "CHIP"}).json())
    return sid, replies


def _draft(client, sid: str):
    return client.post(f"/api/elder/sessions/{sid}/draft")


def _post(client, sid: str, rid: str | None = None):
    return client.post("/api/elder/diaries", json={"request_id": rid or str(uuid.uuid4()), "session_id": sid})


def _sent(room_id: int, kind: str = "DIARY_POSTED") -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).where(Notification.room_id == room_id, Notification.kind == kind))


def test_three_questions_then_post_once_and_family_sees_new(client, monkeypatch):
    room_id = _family_and_elder(client)
    calls = []
    real = coach.diary_draft
    monkeypatch.setattr(coach, "diary_draft", lambda ctx: calls.append(1) or real(ctx))
    sid, replies = _talk(client)
    assert replies[0]["ai"]["text"].startswith("할머니,") and replies[0]["turn_no"] == 1
    assert replies[2]["turn_no"] == 3 and replies[2]["ai"]["suggestions"] == MOODS
    assert replies[3]["state"] == "ENDED" and replies[3]["end_reason"] == "COMPLETED"
    assert "일기" in replies[3]["ai"]["text"]  # "들려주신 이야기로 일기를 써 볼게요"

    draft = _draft(client, sid).json()
    assert draft["mood"] == "SUNNY" and "경로당" in draft["body"] and "맑음" not in draft["body"]
    assert draft["illustration_type"] == "AI_DRAWING"  # mock LLM 은 사물을 모른다 → 기분 그림(D69, 개발은 자리표시)
    assert _draft(client, sid).json() == draft and len(calls) == 1  # 30분 안엔 같은 초안 (LLM·그림 다시 안 부름)

    diaries._drafts[uuid.UUID(sid)].made_at -= timedelta(minutes=DIARY_DRAFT_MIN + 1)
    assert _post(client, sid).json()["code"] == "DRAFT_EXPIRED"  # 30분 지난 초안으로는 못 올린다
    assert _draft(client, sid).status_code == 200 and len(calls) == 2  # 다시 쓰기

    rid = str(uuid.uuid4())
    first = _post(client, sid, rid)
    assert first.status_code == 201, first.text
    diary_id = first.json()["diary_id"]
    assert _post(client, sid, rid).json()["diary_id"] == diary_id  # 같은 request_id 로 다시
    assert _post(client, sid).json()["diary_id"] == diary_id  # 같은 대화를 새 request_id 로
    assert _sent(room_id) == 1  # 가족 1명 → 알림 1건, 다시 눌러도 늘지 않음
    assert _draft(client, sid).json()["code"] == "DIARY_POSTED"  # 올린 뒤 다시 만들면 올린 그림을 덮어쓴다 → 금지
    with SessionLocal() as db:  # 그릴 사물이 없던 일기는 '맑음' 기분 그림, 시드는 대화 번호로 (D69)
        spec = db.scalar(select(Diary.draw_spec).where(Diary.diary_id == diary_id))
        assert spec == {"objects": ["sun", "flower"], "seed": uuid.UUID(sid).int % 2**31}

    listed = client.get(f"/api/rooms/{room_id}/diaries").json()["diaries"]
    assert [d["diary_id"] for d in listed] == [diary_id]
    assert listed[0]["author_name"] == "순자 할머니" and listed[0]["body"] == draft["body"]
    assert listed[0]["read_by_me"] is False  # 가족 홈 '새 일기 1개'

    assert client.post(f"/api/diaries/{diary_id}/read").status_code == 204  # '다 봤어요'
    assert client.post(f"/api/diaries/{diary_id}/read").status_code == 204  # 두 번 눌러도 1행
    assert client.get(f"/api/rooms/{room_id}/diaries").json()["diaries"][0]["read_by_me"] is True

    client.cookies.delete("session")  # 어르신 기기 쿠키만 남김 → 가족 열람 기록 주소는 못 쓴다
    assert client.post(f"/api/diaries/{diary_id}/read").status_code == 401


def test_every_family_member_gets_notice_and_own_read_state(client):
    owner = signup(client)
    room_id = make_room(client)["room_id"]
    add_photos(room_id)
    connect_device(client, room_id)
    inv = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"}).json()
    signup(client)  # 두 번째 가족 (이제 이 client 의 가족 쿠키는 손주)
    token = inv["url"].split("#", 1)[1]
    client.post("/api/invites/accept", json={"token": token, "relation_tag": "GRANDCHILD", "name": "손주"})

    sid, _ = _talk(client)
    _draft(client, sid)
    diary_id = _post(client, sid).json()["diary_id"]
    assert _sent(room_id) == 2  # 가족 2명 → 1건씩

    assert client.post(f"/api/diaries/{diary_id}/read").status_code == 204  # 손주가 '다 봤어요'
    assert client.post(f"/api/diaries/{diary_id}/read").status_code == 204  # 두 번 눌러도 기록은 1번
    assert client.get(f"/api/rooms/{room_id}/diaries").json()["diaries"][0]["read_by_me"] is True
    client.post("/api/auth/login", json={"email": owner["email"], "password": "test1234"})
    assert client.get(f"/api/rooms/{room_id}/diaries").json()["diaries"][0]["read_by_me"] is False  # 방장은 아직
    with SessionLocal() as db:
        assert len(db.get(Diary, diary_id).family_read_by) == 1


def test_not_saved_when_stopped_no_response_or_not_diary(client):
    _family_and_elder(client)
    sid, _ = _talk(client, answers=("집에 있었어요",))
    client.post(f"/api/elder/sessions/{sid}/end", json={"reason": "USER_STOP"})
    assert _draft(client, sid).json()["code"] == "DIARY_NOT_READY"
    assert _post(client, sid).json()["code"] == "DRAFT_EXPIRED"

    sid2, _ = _talk(client, answers=())
    ev = {"input_type": "BUTTON", "event": "NO_RESPONSE"}
    for _ in range(2):
        client.post(f"/api/elder/sessions/{sid2}/turns", json=ev)
    last = client.post(f"/api/elder/sessions/{sid2}/turns", json=ev).json()
    assert last["end_reason"] == "NO_RESPONSE"
    assert "일기" not in last["ai"]["text"]  # 저장하지 않으니 "일기를 써 볼게요"라고 하지 않는다
    assert _draft(client, sid2).status_code == 409

    memory = client.post("/api/elder/sessions", json={"session_id": str(uuid.uuid4()), "kind": "MEMORY"}).json()
    assert _draft(client, memory["session_id"]).status_code == 409


def test_mood_question_keeps_four_chips_on_no_response_and_after_restart(client):
    _family_and_elder(client)
    sid, replies = _talk(client, answers=("집에 있었어요", "혼자요"))
    assert replies[-1]["turn_no"] == 3
    ev = {"input_type": "BUTTON", "event": "NO_RESPONSE"}
    client.post(f"/api/elder/sessions/{sid}/turns", json=ev)
    second = client.post(f"/api/elder/sessions/{sid}/turns", json=ev).json()
    assert second["ai"]["suggestions"] == MOODS  # 2단계여도 기분 칩은 4개 그대로

    sessions._last_reply.pop(uuid.UUID(sid))  # 서버 재시작 흉내 (메모리의 마지막 질문을 잃음)
    got = client.get(f"/api/elder/sessions/{sid}").json()
    assert got["state"] == "CONTINUE" and got["last_ai"]["suggestions"] == MOODS


def test_drawing_waits_then_attaches_and_only_room_members_see_it(client, monkeypatch):
    def fake_llm(name, data, schema):
        if name == "diary_draft":  # 모델은 RAINY 라고 했지만 어르신이 '맑음' 칩을 골랐다 → 칩이 이긴다
            return DiaryDraft(body="시장에서 호박을 샀다.", mood="RAINY", draw_objects=["호박", "장바구니"])
        if name == "diary_buddy":
            return CoachReply(text="오늘은 뭐 하셨어요?", suggestions=["시장", "집"], question_type="NONE")
        raise llm.LlmError(name)

    room_id = _family_and_elder(client)
    monkeypatch.setattr(llm, "call_json", fake_llm)  # coach 의 실제 로직(칩 우선·그릴 사물)은 그대로 돈다
    sid, replies = _talk(client)
    assert replies[0]["ai"]["text"] == "오늘은 뭐 하셨어요?" and replies[2]["ai"]["suggestions"] == MOODS
    draft = _draft(client, sid).json()
    assert draft["mood"] == "SUNNY" and draft["illustration_type"] == "AI_DRAWING"
    assert base64.b64decode(draft["illustration_b64"]).startswith(JPEG_SOI)  # mock 자리표시 그림
    url = f"/api/media/rooms/{room_id}/{sid}.jpg"
    assert client.get(url).status_code == 404  # 올리기 전 그림은 아무도 못 본다

    posted = _post(client, sid).json()
    assert posted["illustration_type"] == "AI_DRAWING" and posted["illustration_url"] == url
    assert client.get(url).content.startswith(JPEG_SOI)  # 가족방 사람(이 client)은 본다
    assert client.get(f"/api/rooms/{room_id}/diaries").json()["diaries"][0]["illustration_url"] == url

    client.cookies.clear()
    signup(client)  # 다른 가족(구성원 아님): 그림·목록·열람 기록 모두 막힘, 일기가 있는지도 모르게 404
    assert client.get(url).status_code == 404
    assert client.get(f"/api/rooms/{room_id}/diaries").status_code == 404
    assert client.post(f"/api/diaries/{posted['diary_id']}/read").status_code == 404


def test_drawing_failure_posts_text_only(client, monkeypatch):
    _family_and_elder(client)
    picked = DiaryDraft(body="호박을 샀다.", mood="SUNNY", draw_objects=["호박"])
    monkeypatch.setattr(coach, "diary_draft", lambda ctx: picked)

    def broken(draw_spec, seed=0):
        raise TimeoutError("workers ai 20초 초과")

    monkeypatch.setattr(image, "generate", broken)
    sid, _ = _talk(client)
    draft = _draft(client, sid).json()
    assert draft["illustration_type"] == "NONE" and draft["illustration_b64"] is None  # 실패 → 글만
    posted = _post(client, sid)
    assert posted.status_code == 201 and posted.json()["illustration_url"] is None


def test_mood_drawing_when_nothing_to_draw_and_seed_per_diary(client, monkeypatch):
    """그릴 사물이 없으면 기분 그림. 시드는 모든 그림이 대화 번호로 — 같은 사물도 일기마다 다른 그림 (D69)."""
    _family_and_elder(client)
    seen = []
    monkeypatch.setattr(image, "generate", lambda spec, seed=0: seen.append((spec["objects"], seed)) or JPEG_SOI)
    sids = []
    for objects in (["pumpkin"], []):
        picked = DiaryDraft(body="장에 다녀왔다.", mood="RAINY", draw_objects=objects)
        monkeypatch.setattr(coach, "diary_draft", lambda ctx, d=picked: d)
        sid, _ = _talk(client)
        assert _draft(client, sid).json()["illustration_type"] == "AI_DRAWING"
        sids.append(sid)
    seeds = [uuid.UUID(s).int % 2**31 for s in sids]
    assert seen == [(["pumpkin"], seeds[0]), (["umbrella", "raindrops"], seeds[1])] and seeds[0] != seeds[1]


def test_photo_diary_is_not_drawn_and_draw_spec_is_sql_null(client, monkeypatch):
    room_id = _family_and_elder(client)
    monkeypatch.setattr(image, "generate", lambda *a: pytest.fail("사진 일기는 그리지 않는다"))
    with SessionLocal() as db:
        photo_id = db.scalar(select(Photo.photo_id).where(Photo.room_id == room_id).limit(1))
    sid, _ = _talk(client, photo_id=photo_id)
    assert _draft(client, sid).json()["illustration_type"] == "PHOTO"
    diary_id = _post(client, sid).json()["diary_id"]
    with SessionLocal() as db:  # 그리지 않은 일기의 draw_spec 은 SQL NULL (JSON null 아님)
        assert db.scalar(select(Diary.draw_spec.is_(None)).where(Diary.diary_id == diary_id))


def test_read_aloud_tts_failure_alerts_family_once(client, monkeypatch):
    """일기 낭독 TTS 가 실패하면 음성 없이(화면이 브라우저 TTS 로 읽음) + 가족 알림 TTS_ERROR 는 그 대화에 1건 (D5)."""
    room_id = _family_and_elder(client)

    def read_aloud_fails(text, speed):  # 대화 질문은 되고 낭독('… 이대로 올릴까요?')만 실패
        if text.endswith("이대로 올릴까요?"):
            raise httpx.ReadTimeout("slow")
        return None

    monkeypatch.setattr(tts, "synthesize", read_aloud_fails)
    sid, _ = _talk(client)
    assert _draft(client, sid).json()["audio_b64"] is None and _sent(room_id, "TTS_ERROR") == 1
    diaries._drafts[uuid.UUID(sid)].made_at -= timedelta(minutes=DIARY_DRAFT_MIN + 1)  # 30분 지나 다시 만들다 또 실패
    assert _draft(client, sid).status_code == 200 and _sent(room_id, "TTS_ERROR") == 1


def test_fallback_draft_drops_banned_words_and_reads_spoken_mood():
    """LLM 이 없거나 실패할 때의 초안: 금지어가 든 답은 빼고(NFR-DE-003), 말로 한 기분 칩 이름도 알아듣는다."""
    turns = [
        {"speaker": "AI", "text": "오늘은 뭐 하셨어요?"},
        {"speaker": "ELDER", "text": "병원 가서 검사 결과 들었어"},
        {"speaker": "AI", "text": "누구랑 계셨어요?"},
        {"speaker": "ELDER", "text": "딸이랑 갔어"},
        {"speaker": "AI", "text": "오늘 기분은 어떠셨어요?"},
        {"speaker": "ELDER", "text": "맑음이요."},
    ]
    d = coach.diary_draft(coach.CoachContext("순자", "할머니", None, turns))  # conftest: LLM_PROVIDER=mock → 고정 경로
    assert not any(w in d.body for w in BANNED_WORDS) and "딸이랑" in d.body
    assert d.mood == "SUNNY" and "맑음" not in d.body
    assert [coach.mood_of(t) for t in ("비요", "달이에요", "비 와요", "좋았어")] == ["RAINY", "MOON", None, None]


def test_mock_drawing_only_in_dev(monkeypatch):
    assert image.generate({"objects": ["호박"]}).startswith(JPEG_SOI)
    monkeypatch.setattr(settings, "APP_ENV", "deploy")
    assert image.generate({"objects": ["호박"]}) is None  # 배포에서 가짜 그림이 진짜 그림일기로 가족에게 가지 않게


def test_cloudflare_drawing_fixed_style_and_reencoded_jpeg(monkeypatch):
    """실제 제공자(D37): 고정 화풍에 사물 이름만 끼운 multipart 1회, 받은 그림은 JPEG 로 다시 인코딩.
    유료 API 는 부르지 않는다(httpx.post 를 바꿔 끼움)."""
    sent = {}
    reply = {"status": 200, "size": (8, 8)}

    def fake_post(url, headers, files, timeout):
        sent.update(url=url, auth=headers["Authorization"], fields={k: v[1] for k, v in files.items()}, timeout=timeout)
        png = io.BytesIO()
        Image.new("RGB", reply["size"], (200, 100, 50)).save(png, "PNG")
        body = {"success": True, "result": {"image": base64.b64encode(png.getvalue()).decode()}}
        return httpx.Response(reply["status"], json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(image.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "IMAGE_PROVIDER", "cloudflare")
    monkeypatch.setattr(settings, "CF_ACCOUNT_ID", "acct")
    monkeypatch.setattr(settings, "CF_API_TOKEN", "tok")
    out = image.generate({"objects": ["찻잔", "화투\n패"]}, seed=7)
    assert out.startswith(JPEG_SOI)  # PNG 로 와도 JPEG
    assert sent["url"].endswith("/accounts/acct/ai/run/@cf/black-forest-labs/flux-2-klein-4b")
    assert sent["auth"] == "Bearer tok" and sent["timeout"] == 20
    assert "찻잔, 화투 패" in sent["fields"]["prompt"] and "No people" in sent["fields"]["prompt"]
    assert sent["fields"]["seed"] == "7" and sent["fields"]["width"] == "768"
    assert image.generate({"objects": []}) is None  # 그릴 것이 없으면 부르지 않는다

    reply["size"] = (4096, 8)  # 너무 큰 그림은 풀기 전에 거절 → 글만
    with pytest.raises(ValueError):
        image.generate({"objects": ["찻잔"]})
    reply.update(status=429, size=(8, 8))  # 하루 무료 한도 초과 → 예외 → 글만
    with pytest.raises(httpx.HTTPStatusError):
        image.generate({"objects": ["찻잔"]})

    monkeypatch.setattr(settings, "CF_API_TOKEN", "")
    with pytest.raises(RuntimeError):  # 키가 없으면 예외 → diaries._draw 가 글만 게시
        image.generate({"objects": ["찻잔"]})
