"""웹 푸시: 암호화 정답 대조(RFC 8291)·VAPID 서명·구독 API(인증·검사·SSRF)·어느 알림에 보내는지·죽은 구독 지우기·로그.

진짜 푸시 서버는 부르지 않는다 — outbox 가 httpx 의 가짜 전송로로 요청을 받아 쌓는다.
"""

import json
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import PUSH_JWT_SEC, PUSH_SUBS_PER_USER, PUSH_TTL_SEC, ROOT, TZ, now_kst, settings, today_kst
from app.db import SessionLocal, engine
from app.models import DailyPick, FamilyRoom, Notification, PushSubscription, RoomMember
from app.routers.devices import notify_family
from app.services import push, scheduler
from scripts.vapid_keys import generate
from tests.conftest import connect_device, make_room, setup_elder, signup
from tests.test_diary import _draft, _post, _talk
from tests.test_mood_signal import _say, _start

# RFC 8291 5절 예시와 부록 A 의 값 그대로 (https://www.rfc-editor.org/rfc/rfc8291.txt — 줄바꿈·빈칸만 뺐다)
RFC_PLAINTEXT = "V2hlbiBJIGdyb3cgdXAsIEkgd2FudCB0byBiZSBhIHdhdGVybWVsb24"
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
RFC_UA_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_HEADER = (  # 부록 A '86-octet header'
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
)
RFC_CIPHERTEXT = "8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ"
RFC_BODY = (  # 5절의 요청 본문
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
    "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)

FCM = "https://fcm.googleapis.com/fcm/send/"
SECRET = "파란우산비밀문장"


def _private_key(b64: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(push.unb64u(b64), "big"), ec.SECP256R1())


def _point(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _decrypt(body: bytes, ua_private: ec.EllipticCurvePrivateKey, auth: bytes) -> bytes:
    """받는 쪽(브라우저)의 계산 — RFC 8291 3.4절 'For a user agent'."""
    salt, record_size, key_len = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_public = body[21 : 21 + key_len]
    ecdh = ua_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    ikm = push._hkdf(auth, ecdh, b"WebPush: info\x00" + _point(ua_private) + as_public, 32)
    cek = push._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = push._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, body[21 + key_len :], None)
    assert record_size == 4096 and key_len == 65 and plain.endswith(b"\x02")
    return plain[:-1]


class Phone:
    """브라우저 한 대 흉내 — 구독(주소·키)을 만들고, 받은 푸시 본문을 풀어 본다."""

    def __init__(self, base: str = FCM):
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = base + uuid.uuid4().hex
        # PushSubscription.toJSON() 과 같은 모양
        self.json = {
            "endpoint": self.endpoint,
            "expirationTime": None,
            "keys": {"p256dh": push.b64u(_point(self.private)), "auth": push.b64u(self.auth)},
        }

    def open(self, request: httpx.Request) -> dict:
        return json.loads(_decrypt(request.content, self.private, self.auth))

    def rows(self) -> list[PushSubscription]:
        with SessionLocal() as db:
            return db.scalars(select(PushSubscription).where(PushSubscription.endpoint == self.endpoint)).all()


class Outbox:
    """가짜 푸시 서비스 — 받은 요청을 쌓고, 주소별로 정해 둔 상태 코드(기본 201)로 답한다."""

    def __init__(self):
        self.sent: list[httpx.Request] = []
        self.status: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        status = self.status.get(str(request.url), 201)
        return httpx.Response(status, headers={"Location": "http://169.254.169.254/"} if status == 307 else None)

    def to(self, phone: "Phone") -> list[httpx.Request]:
        """그 폰으로 간 요청만 — 예약 작업은 다른 테스트가 남긴 가족방에도 보내므로 내 폰 것만 골라 본다."""
        return [r for r in self.sent if str(r.url) == phone.endpoint]


class Inline:
    """작업 스레드 대신 그 자리에서 보낸다 — 테스트가 결과를 바로 본다."""

    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture
def outbox(monkeypatch):
    """VAPID 키를 넣어 푸시를 켜고, 요청이 진짜 서버 대신 Outbox 로 가게 한다(시간 제한·리다이렉트 설정은 그대로)."""
    public, private = generate()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:push-test@test.local")
    box = Outbox()
    fake = httpx.Client(
        transport=httpx.MockTransport(box), timeout=push._http.timeout, follow_redirects=push._http.follow_redirects
    )
    monkeypatch.setattr(push, "_http", fake)
    monkeypatch.setattr(push, "_pool", Inline())
    return box


def _family_phone(client) -> Phone:
    phone = Phone()
    assert client.post("/api/push/subscribe", json=phone.json).json() == {"ok": True}
    return phone


def _notify(room_id: int, kind: str = "DIARY_POSTED", title: str = "알림 제목", **kwargs) -> None:
    with SessionLocal() as db:
        notify_family(db, room_id, kind, title, **kwargs)
        db.commit()


def _at(monkeypatch, hour: int, minute: int = 0) -> datetime:
    now = datetime.combine(today_kst(), time(hour, minute), tzinfo=TZ)
    monkeypatch.setattr(scheduler, "now_kst", lambda: now)
    monkeypatch.setattr(push, "now_kst", lambda: now)
    return now


def _reminders(room_id: int, kind: str) -> list[Notification]:
    with SessionLocal() as db:
        return db.scalars(select(Notification).where(Notification.room_id == room_id, Notification.kind == kind)).all()


# ---- 암호화·서명


def test_encrypt_matches_rfc8291_example():
    body = push.encrypt(
        push.unb64u(RFC_PLAINTEXT),
        push.unb64u(RFC_UA_PUBLIC),
        push.unb64u(RFC_AUTH),
        salt=push.unb64u(RFC_SALT),
        as_private=_private_key(RFC_AS_PRIVATE),
    )
    assert body == push.unb64u(RFC_HEADER) + push.unb64u(RFC_CIPHERTEXT)
    assert push.b64u(body) == RFC_BODY
    # 받는 쪽 계산(이 파일의 _decrypt)도 문서의 받는 쪽 개인 키로 같은 글을 얻는다
    plain = _decrypt(push.unb64u(RFC_BODY), _private_key(RFC_UA_PRIVATE), push.unb64u(RFC_AUTH))
    assert plain == b"When I grow up, I want to be a watermelon"


def test_encrypt_uses_fresh_salt_and_key_each_time():
    phone = Phone()
    first, second = (push.encrypt(b"same", _point(phone.private), phone.auth) for _ in range(2))
    assert first != second and first[:16] != second[:16] and first[21:86] != second[21:86]
    assert _decrypt(first, phone.private, phone.auth) == _decrypt(second, phone.private, phone.auth) == b"same"


def test_vapid_header_verifies_with_the_public_key(outbox):
    token, key = re.fullmatch(r"vapid t=(\S+), k=(\S+)", push.vapid(FCM + "abc")).groups()
    assert key == settings.VAPID_PUBLIC_KEY
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64u(key))
    claims = jwt.decode(token, public, algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"] == "mailto:push-test@test.local"
    assert 0 < claims["exp"] - now_kst().timestamp() <= PUSH_JWT_SEC <= 24 * 3600  # RFC 8292: 24시간 안
    assert jwt.get_unverified_header(token) == {"alg": "ES256", "typ": "JWT"}
    other = ec.generate_private_key(ec.SECP256R1()).public_key()
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, other, algorithms=["ES256"], audience="https://fcm.googleapis.com")


# ---- 구독 API


def test_key_is_null_until_vapid_keys_are_set(client, outbox, monkeypatch):
    assert client.get("/api/push/key").json() == {"public_key": settings.VAPID_PUBLIC_KEY}
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    assert client.get("/api/push/key").json() == {"public_key": None}


def test_subscribe_needs_the_right_cookie(client):
    phone = Phone()
    for path in ("/api/push/subscribe", "/api/push/unsubscribe"):
        r = client.post(path, json=phone.json)
        assert (r.status_code, r.json()["code"]) == (401, "AUTH_REQUIRED")
    r = client.post("/api/elder/push/subscribe", json=phone.json)
    assert (r.status_code, r.json()["code"]) == (401, "DEVICE_REQUIRED")
    signup(client)  # 가족 로그인으로는 어르신 기기 구독을 만들 수 없다
    assert client.post("/api/elder/push/subscribe", json=phone.json).status_code == 401
    assert phone.rows() == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",  # https 아님
        "https://example.com/fcm/send/abc",  # 목록에 없는 호스트
        "https://127.0.0.1/fcm/send/abc",
        "https://169.254.169.254/latest/meta-data/",  # 클라우드 내부 주소
        "https://db:5432/",
        "https://fcm.googleapis.com@example.com/abc",  # 사용자 정보로 호스트 속이기
        "https://fcm.googleapis.com.example.com/abc",  # 닮은 이름
        "https://example.com\\.push.apple.com/abc",  # 해석기마다 호스트가 달라지는 글자
        "https://xpush.apple.com/abc",
        "https://push.apple.com/abc",  # *.push.apple.com 만
        "https://fcm.googleapis.com:8443/abc",  # 다른 포트
        "https://FCM.googleapis.com/abc",
        "https://fcm.googleapis.com/abc#frag",
        "https://fcm.googleapis.com",
    ],
)
def test_rejects_endpoints_outside_known_push_services(client, endpoint):
    setup_elder(client)  # 가족 쿠키 + 기기 쿠키
    body = Phone().json | {"endpoint": endpoint}
    for path in ("/api/push/subscribe", "/api/elder/push/subscribe"):
        r = client.post(path, json=body)
        assert (r.status_code, r.json()["code"]) == (400, "PUSH_ENDPOINT_INVALID"), endpoint
    with SessionLocal() as db:
        assert db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint)) is None


@pytest.mark.parametrize(
    "endpoint",
    [
        FCM + "dA1:APA91b-_x",
        "https://updates.push.services.mozilla.com/wpush/v2/gAAAAAB=",
        "https://web.push.apple.com/QOkabc",
        "https://wns2-by3p.notify.windows.com/w/?token=BQYA%2b%3d",
    ],
)
def test_accepts_known_push_services(client, endpoint):
    signup(client)
    phone = Phone()
    phone.endpoint = phone.json["endpoint"] = f"{endpoint}{uuid.uuid4().hex}"
    assert client.post("/api/push/subscribe", json=phone.json).status_code == 200
    assert len(phone.rows()) == 1


def test_rejects_malformed_keys_and_long_endpoint(client):
    signup(client)
    good = Phone().json
    bad_bodies = [
        good | {"keys": good["keys"] | {"p256dh": "짧음"}},
        good | {"keys": good["keys"] | {"p256dh": "A" + good["keys"]["p256dh"][1:]}},  # 0x04 로 시작하지 않는 키
        good | {"keys": good["keys"] | {"p256dh": good["keys"]["p256dh"] + "AAAA"}},
        good | {"keys": good["keys"] | {"auth": good["keys"]["auth"][:-1] + "+"}},  # base64url 글자가 아님
        good | {"keys": {"p256dh": good["keys"]["p256dh"]}},
        {"endpoint": good["endpoint"]},
        good | {"endpoint": FCM + "a" * 1000},
    ]
    for body in bad_bodies:
        r = client.post("/api/push/subscribe", json=body)
        assert (r.status_code, r.json()["code"]) == (422, "VALIDATION"), body
    with SessionLocal() as db:
        assert db.scalar(select(PushSubscription).where(PushSubscription.endpoint == good["endpoint"])) is None


def test_same_browser_follows_whoever_is_logged_in(client):
    first = signup(client)
    phone = _family_phone(client)
    assert client.post("/api/push/subscribe", json=phone.json).status_code == 200  # 두 번 눌러도 1줄
    assert [(s.user_id, s.room_id) for s in phone.rows()] == [(first["user_id"], None)]
    second = signup(client)  # 같은 브라우저에 다른 사람이 로그인
    assert client.post("/api/push/unsubscribe", json={"endpoint": phone.endpoint}).json() == {"ok": True}
    assert len(phone.rows()) == 1  # 남의 줄은 지우지 못한다(답은 같다)
    assert client.post("/api/push/subscribe", json=phone.json).status_code == 200
    assert [s.user_id for s in phone.rows()] == [second["user_id"]]
    assert client.post("/api/push/unsubscribe", json={"endpoint": phone.endpoint}).json() == {"ok": True}
    assert phone.rows() == []


def test_family_keeps_only_the_latest_browsers(client):
    user = signup(client)

    def kept():
        with SessionLocal() as db:
            return set(db.scalars(select(PushSubscription.endpoint).where(PushSubscription.user_id == user["user_id"])))

    phones = [_family_phone(client) for _ in range(PUSH_SUBS_PER_USER + 1)]
    assert kept() == {p.endpoint for p in phones[1:]}  # 하나 넘침 → 가장 오래전에 등록한 것이 빠진다
    assert client.post("/api/push/subscribe", json=phones[1].json).status_code == 200  # 다시 등록 = 방금 쓴 브라우저
    latest = _family_phone(client)
    assert kept() == {p.endpoint for p in [phones[1], *phones[3:], latest]}  # 이번에는 phones[2] 가 빠진다


def test_elder_subscription_is_one_per_room_and_dropped_with_the_device(client):
    room_id = setup_elder(client)["room_id"]
    old, new = Phone(), Phone()

    def room_endpoints():
        with SessionLocal() as db:
            return db.scalars(select(PushSubscription.endpoint).where(PushSubscription.room_id == room_id)).all()

    assert client.post("/api/elder/push/subscribe", json=old.json).json() == {"ok": True}
    assert client.post("/api/elder/push/subscribe", json=new.json).status_code == 200  # 브라우저가 구독을 새로 만듦
    assert room_endpoints() == [new.endpoint]
    assert new.rows()[0].user_id is None
    connect_device(client, room_id)  # 새 기기 연결 → 옛 기기 구독은 지운다
    assert room_endpoints() == []
    assert client.post("/api/elder/push/subscribe", json=new.json).status_code == 200
    assert client.delete(f"/api/rooms/{room_id}/device").status_code == 200  # 연결 해제
    assert room_endpoints() == []


def test_db_wants_exactly_one_owner(client):
    user = signup(client)
    room_id = make_room(client)["room_id"]
    for owner in ({}, {"user_id": user["user_id"], "room_id": room_id}):
        with SessionLocal() as db, pytest.raises(IntegrityError):
            db.add(PushSubscription(endpoint=FCM + uuid.uuid4().hex, p256dh="p", auth="a", **owner))
            db.commit()


def test_migration_is_the_same_table_and_safe_to_rerun():
    schema = (ROOT / "db" / "schema.sql").read_text("utf-8")
    migration = (ROOT / "db" / "migrations" / "20261119_push_subscriptions.sql").read_text("utf-8")
    start = schema.index("CREATE TABLE push_subscriptions")
    ddl = schema[start : schema.index(");", start) + 2]
    assert ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ") in migration
    with engine.begin() as conn:
        conn.exec_driver_sql(migration)
        conn.exec_driver_sql(migration)


# ---- 가족 푸시: 어느 알림을, 누구에게, 무엇을


def test_family_push_only_for_diary_weekly_and_urgent(client, outbox):
    signup(client)
    room_id = make_room(client)["room_id"]
    phone = _family_phone(client)
    links = {
        "DIARY_POSTED": "HOME_001",
        "WEEKLY_READY": "WEEKLY_001",
        "MOOD_URGENT": "HOME_001",
        "MOOD_LOW_2D": "HOME_001",
        "NO_RECORD_2D": "HOME_001",  # 이틀째 기록 없음도 폰으로 (11/19)
    }
    others = ["DEVICE_CONNECTED", "PERMISSION_OFF", "SESSION_ERROR_3X", "TTS_ERROR", "PICK_SKIPPED_2X"]
    for kind in [*links, *others]:
        _notify(room_id, kind, f"제목 {kind}", body=SECRET, link=links.get(kind, "HOME_001"))
    got = {phone.open(r)["tag"].split("-")[0]: (phone.open(r), r.headers) for r in outbox.sent}
    assert len(outbox.sent) == 5 and set(got) == set(links)
    # '이틀째 기록 없음'은 알림 제목에 어르신 이름이 들어 있어, 폰(잠금 화면)에는 이름 없는 제목으로 간다
    assert got["NO_RECORD_2D"][0]["title"] == push.NO_RECORD_TITLE
    # '전화 한 통 드려 보세요'(기운 없는 날·마음 체크)도 제목만, 급하게 전하지는 않는다 (11/19)
    low, low_headers = got["MOOD_LOW_2D"]
    assert "body" not in low and low_headers["urgency"] == "normal"

    diary, headers = got["DIARY_POSTED"]  # 일기 알림의 body(일기 글)는 보내지 않는다 — 제목만
    assert diary == {"title": "제목 DIARY_POSTED", "url": f"/?room={room_id}", "tag": f"DIARY_POSTED-{room_id}"}
    assert (headers["urgency"], headers["ttl"], headers["content-encoding"]) == (
        "normal",
        str(PUSH_TTL_SEC),
        "aes128gcm",
    )
    assert headers["authorization"].startswith("vapid t=")
    weekly, _ = got["WEEKLY_READY"]
    assert weekly == {"title": "제목 WEEKLY_READY", "url": f"/weekly/{room_id}", "tag": f"WEEKLY_READY-{room_id}"}
    urgent, headers = got["MOOD_URGENT"]  # 위급 알림도 제목만(이름·상태는 잠금 화면에 안 보이게), 급하게
    assert "body" not in urgent and urgent["url"] == f"/?room={room_id}" and headers["urgency"] == "high"


def test_no_record_push_rings_once_per_quiet_stretch(client, outbox, monkeypatch):
    """이틀째 기록 없음: 알림 목록에는 날마다 남기되 폰은 조용해진 첫날만 울린다 — 날마다 울리면 알림을 꺼 버린다."""
    signup(client)
    room_id = make_room(client)["room_id"]
    phone = _family_phone(client)
    now = _at(monkeypatch, 19)
    with SessionLocal() as db:
        room = db.get(FamilyRoom, room_id)
        room.device_token_hash, room.device_connected_at = "0" * 64, now - timedelta(days=3)
        db.commit()
    scheduler.no_record_alerts()
    assert [phone.open(r)["title"] for r in outbox.sent] == [push.NO_RECORD_TITLE]
    monkeypatch.setattr(scheduler, "now_kst", lambda: now + timedelta(days=1))
    scheduler.no_record_alerts()
    assert len(outbox.sent) == 1 and len(_reminders(room_id, "NO_RECORD_2D")) == 2


def test_unknown_link_opens_the_app_start(client, outbox):
    signup(client)
    room_id = make_room(client)["room_id"]
    phone = _family_phone(client)
    _notify(room_id, "DIARY_POSTED")
    assert phone.open(outbox.sent[0])["url"] == "/start"


def test_push_goes_to_current_members_browsers_only(client, outbox):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    owner_phones = [_family_phone(client), _family_phone(client)]  # 폰과 태블릿
    elder = Phone()
    assert client.post("/api/elder/push/subscribe", json=elder.json).status_code == 200
    token = client.post(f"/api/rooms/{room_id}/invites", json={"kind": "FAMILY"}).json()["url"].split("#", 1)[1]
    removed = signup(client)
    assert client.post("/api/invites/accept", json={"token": token, "relation_tag": "GRANDCHILD"}).status_code == 200
    _family_phone(client)
    with SessionLocal() as db:
        member = db.scalar(
            select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.user_id == removed["user_id"])
        )
        member.removed_at = now_kst()
        db.commit()
    signup(client)  # 가족방과 상관없는 사람
    _family_phone(client)
    _notify(room_id)
    assert sorted(str(r.url) for r in outbox.sent) == sorted(p.endpoint for p in owner_phones)


def test_elder_diary_pushes_the_title_only_and_logs_no_endpoint(client, outbox, caplog):
    caplog.set_level(logging.DEBUG)
    room_id = setup_elder(client)["room_id"]
    phone = _family_phone(client)
    sid, _ = _talk(client, answers=(SECRET, SECRET, "좋았어요"))
    assert SECRET in _draft(client, sid).json()["body"]
    assert _post(client, sid).status_code == 201
    [request] = outbox.sent
    assert str(request.url) == phone.endpoint
    payload = phone.open(request)
    diary_id = _post(client, sid).json()["diary_id"]  # 같은 일기를 다시 돌려준다 — 푸시는 더 안 간다
    assert len(outbox.sent) == 1
    assert payload == {
        "title": "순자 할머니 일기가 왔어요",
        "url": f"/diaries/{diary_id}",  # 누르면 그 일기 (11/23 link_id)
        "tag": f"DIARY_POSTED-{room_id}",
    }
    assert SECRET not in json.dumps(payload, ensure_ascii=False)
    # 로그에는 구독 번호·상태 코드만 — 주소·키는 없다 (D15)
    assert f"push sub={phone.rows()[0].subscription_id} status=201" in caplog.text
    keys = phone.json["keys"]
    for hidden in (
        phone.endpoint,
        phone.endpoint[len(FCM) :],
        keys["p256dh"],
        keys["auth"],
        settings.VAPID_PRIVATE_KEY,
    ):
        assert hidden not in caplog.text
    assert SECRET not in caplog.text


def test_httpx_request_log_drops_push_urls_only(caplog):
    caplog.set_level(logging.INFO)
    for url in (FCM + "token-123", "https://web.push.apple.com/token-456", "https://tts.example.com/v1/speak"):
        logging.getLogger("httpx").info('HTTP Request: %s %s "%s %d %s"', "POST", httpx.URL(url), "HTTP/1.1", 201, "OK")
    assert "token-123" not in caplog.text and "token-456" not in caplog.text
    assert "https://tts.example.com/v1/speak" in caplog.text  # 다른 요청 줄은 그대로


def test_risk_words_push_urgently_without_what_was_said(client, outbox):
    ctx = setup_elder(client)
    phone = _family_phone(client)
    said = "요즘은 정말 죽고 싶어요"
    _say(client, _start(client, ctx), said)
    [request] = outbox.sent
    payload = phone.open(request)
    assert payload == {
        "title": "지금 전화 한 통 드려 보세요",  # 이름·상태가 든 body 는 푸시에 싣지 않는다
        "url": f"/?room={ctx['room_id']}",
        "tag": f"MOOD_URGENT-{ctx['room_id']}",
    }
    assert request.headers["urgency"] == "high"
    assert said not in json.dumps(payload, ensure_ascii=False)


# ---- 보내기: 키 없음·되돌림·죽은 구독·리다이렉트


def test_nothing_is_sent_without_vapid_keys(client, outbox, monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    signup(client)
    room_id = make_room(client)["room_id"]
    _family_phone(client)
    with SessionLocal() as db:
        notify_family(db, room_id, "DIARY_POSTED", "알림 제목")
        assert push._QUEUED not in db.info  # 예약조차 하지 않는다
        db.commit()
    assert outbox.sent == []
    assert len(_reminders(room_id, "DIARY_POSTED")) == 1  # 앱 안 알림은 그대로 남는다


def test_rolled_back_notification_is_not_pushed(client, outbox):
    signup(client)
    room_id = make_room(client)["room_id"]
    phone = _family_phone(client)
    with SessionLocal() as db:
        notify_family(db, room_id, "DIARY_POSTED", "되돌린 알림")
        db.rollback()
        notify_family(db, room_id, "WEEKLY_READY", "남은 알림", link="WEEKLY_001")
        assert outbox.sent == []  # commit 전에는 나가지 않는다
        db.commit()
    assert [phone.open(r)["title"] for r in outbox.sent] == ["남은 알림"]
    with SessionLocal() as db:  # commit 없이 닫힌 작업
        notify_family(db, room_id, "DIARY_POSTED", "닫힌 알림")
    with SessionLocal() as db:
        db.commit()
    assert len(outbox.sent) == 1


@pytest.mark.parametrize("status,kept", [(201, True), (404, False), (410, False), (403, True), (500, True)])
def test_gone_subscription_is_deleted(client, outbox, caplog, status, kept):
    caplog.set_level(logging.INFO)
    signup(client)
    room_id = make_room(client)["room_id"]
    gone, fine = _family_phone(client), _family_phone(client)
    outbox.status[gone.endpoint] = status
    _notify(room_id)
    assert len(outbox.sent) == 2
    assert bool(gone.rows()) is kept and len(fine.rows()) == 1
    assert f"status={status}" in caplog.text


def test_worker_thread_gets_plain_values(client, outbox, monkeypatch):
    """진짜 작업 스레드로 보내도 된다 — 스레드에는 값만 넘어가고, 죽은 구독은 새 DB 연결로 지운다."""
    pool = ThreadPoolExecutor(1)
    monkeypatch.setattr(push, "_pool", pool)
    signup(client)
    room_id = make_room(client)["room_id"]
    phone = _family_phone(client)
    outbox.status[phone.endpoint] = 410
    _notify(room_id, title="스레드로 보낸 알림")
    pool.shutdown(wait=True)
    assert [phone.open(r)["title"] for r in outbox.sent] == ["스레드로 보낸 알림"]
    assert phone.rows() == []


def test_send_failure_is_logged_by_type_only(client, outbox, monkeypatch, caplog):
    def broken(request):
        raise httpx.ConnectTimeout(f"timed out {request.url}")

    monkeypatch.setattr(push, "_http", httpx.Client(transport=httpx.MockTransport(broken)))
    signup(client)
    room_id = make_room(client)["room_id"]
    phone = _family_phone(client)
    _notify(room_id)  # 예외가 밖으로 나오지 않는다
    assert "error=ConnectTimeout" in caplog.text and phone.endpoint not in caplog.text
    assert len(phone.rows()) == 1


def test_redirect_is_not_followed(client, outbox):
    assert push._http.follow_redirects is False
    signup(client)
    room_id = make_room(client)["room_id"]
    phone = _family_phone(client)
    outbox.status[phone.endpoint] = 307
    _notify(room_id)
    assert [str(r.url) for r in outbox.sent] == [phone.endpoint]  # Location 으로 다시 보내지 않았다
    assert len(phone.rows()) == 1


# ---- 어르신 시간 알림 (FR-NT-002)


def test_elder_gets_memory_and_diary_push_at_most_twice_a_day(client, outbox, monkeypatch):
    room_id = setup_elder(client)["room_id"]  # 홈을 열어 오늘의 한 장(PENDING)이 있다
    elder = Phone()
    assert client.post("/api/elder/push/subscribe", json=elder.json).status_code == 200
    family = _family_phone(client)
    with SessionLocal() as db:
        db.get(FamilyRoom, room_id).memory_time = time(9)
        db.commit()
    _at(monkeypatch, 8, 1)
    scheduler.memory_reminders()
    assert outbox.to(elder) == [] and _reminders(room_id, "MEMORY_REMINDER") == []  # 추억 시간 전
    sent_at = _at(monkeypatch, 9, 1)
    scheduler.memory_reminders()
    scheduler.memory_reminders()
    _at(monkeypatch, 10, 1)
    scheduler.memory_reminders()
    _at(monkeypatch, 19)
    scheduler.diary_reminders()
    scheduler.diary_reminders()
    _at(monkeypatch, 20, 1)
    scheduler.memory_reminders()

    assert outbox.to(family) == []  # 가족 브라우저로는 어르신 알림이 가지 않는다
    memory, diary = outbox.to(elder)  # 하루 2건뿐
    assert elder.open(memory) == {
        "title": "오늘의 한 장이 기다리고 있어요",
        "url": "/elder/today",
        "tag": "MEMORY_REMINDER",
    }
    assert elder.open(diary) == {
        "title": "오늘 하루 이야기를 들려주세요",
        "url": "/elder/diary",
        "tag": "DIARY_REMINDER",
    }
    assert (memory.headers["ttl"], memory.headers["urgency"]) == (str(15 * 3600 - 60), "normal")  # 09:01 → 자정까지만
    assert diary.headers["ttl"] == str(5 * 3600)
    [row] = _reminders(room_id, "MEMORY_REMINDER")
    assert (row.target_type, row.target_user_id, row.link_screen, row.sent_at) == (
        "ELDER",
        None,
        "ELDER_TODAY_001",
        sent_at,
    )
    assert row.title == "순자 할머니, 오늘의 한 장이 기다리고 있어요"
    assert len(_reminders(room_id, "DIARY_REMINDER")) == 1


@pytest.mark.parametrize("case", ["waiting", "completed", "skipped", "no_pick", "unconnected", "closed"])
def test_memory_reminder_only_while_the_pick_is_waiting(client, outbox, monkeypatch, case):
    ctx = setup_elder(client)
    room_id = ctx["room_id"]
    elder = Phone()
    assert client.post("/api/elder/push/subscribe", json=elder.json).status_code == 200
    with SessionLocal() as db:
        pick, room = db.get(DailyPick, ctx["pick"]["pick_id"]), db.get(FamilyRoom, room_id)
        room.memory_time = time(9)
        if case in ("completed", "skipped"):
            pick.status = case.upper()
        elif case == "no_pick":
            db.delete(pick)
        elif case == "unconnected":
            room.device_token_hash = None
        elif case == "closed":
            room.status = "CLOSED"
        db.commit()
    _at(monkeypatch, 9, 1)
    scheduler.memory_reminders()
    expected = 1 if case == "waiting" else 0  # 'waiting' 은 견줄 기준 — 아무것도 안 바꾸면 알림이 간다
    assert len(outbox.to(elder)) == expected and len(_reminders(room_id, "MEMORY_REMINDER")) == expected


@pytest.mark.parametrize("hour,minute,expected", [(10, 59, 1), (11, 1, 0), (23, 1, 0)])
def test_memory_reminder_is_not_sent_hours_late(client, outbox, monkeypatch, hour, minute, expected):
    """추억 시간(9시)에 서버가 꺼져 있었으면 2시간 안에 켜졌을 때만 보낸다 — 밤에 뒤늦게 어르신 폰을 울리지 않는다."""
    room_id = setup_elder(client)["room_id"]
    elder = Phone()
    assert client.post("/api/elder/push/subscribe", json=elder.json).status_code == 200
    with SessionLocal() as db:
        db.get(FamilyRoom, room_id).memory_time = time(9)
        db.commit()
    _at(monkeypatch, hour, minute)
    scheduler.memory_reminders()
    assert len(outbox.to(elder)) == expected and len(_reminders(room_id, "MEMORY_REMINDER")) == expected


def test_midnight_memory_time_still_gets_its_reminder(client, outbox, monkeypatch):
    room_id = setup_elder(client)["room_id"]  # 테스트 가족방의 추억 시간은 00:00 (conftest add_photos)
    elder = Phone()
    assert client.post("/api/elder/push/subscribe", json=elder.json).status_code == 200
    _at(monkeypatch, 0, 1)
    scheduler.memory_reminders()
    assert len(outbox.to(elder)) == 1 and len(_reminders(room_id, "MEMORY_REMINDER")) == 1


def test_diary_reminder_push_is_not_sent_hours_late(client, outbox, monkeypatch):
    """밤에 서버를 다시 띄우면(기동 보정) 일기 알림 줄은 만들되 어르신 폰은 울리지 않는다 (11/19 — 배포가 주로 저녁)."""
    room_id = setup_elder(client)["room_id"]
    elder = Phone()
    assert client.post("/api/elder/push/subscribe", json=elder.json).status_code == 200
    _at(monkeypatch, 22)
    scheduler.diary_reminders()
    assert outbox.to(elder) == [] and len(_reminders(room_id, "DIARY_REMINDER")) == 1
