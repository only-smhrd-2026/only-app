"""웹 푸시 (FR-NT-002·003) — 앱이 닫혀 있어도 폰에 알림이 뜨게 브라우저의 푸시 서비스(FCM·애플·모질라)로 보낸다.

- 받는 곳: push_subscriptions 한 줄 = 브라우저 하나. 가족은 user_id, 어르신 기기는 room_id.
- 무엇을: 가족에게는 일기 도착·주간 이야기 도착·위급 알림만(FAMILY_KINDS), 어르신께는 추억·일기 시간 알림(ELDER_PUSH).
  잠금 화면에 보이므로 일기 글·어르신 말은 넣지 않는다 — 제목만.
- 어떻게(라이브러리 없이 직접): 본문은 RFC 8291(aes128gcm)로 그 브라우저만 풀 수 있게 암호화하고,
  '이 서버가 보냈다'는 표시는 RFC 8292 VAPID(ES256 JWT)로 한다.
- 언제: queue_* 는 예약만 한다. 그 DB 작업이 commit 된 뒤에 작업 스레드 2개가 보낸다 —
  요청을 붙잡지 않고, 되돌려진(rollback) 알림은 푸시도 나가지 않는다.
- VAPID 키가 없으면(내 PC·테스트) 아무것도 하지 않는다.
- 로그에는 구독 번호·상태 코드만. 주소(endpoint)는 그 폰으로 가는 표라서 남기지 않는다 (D15).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.config import PUSH_JWT_SEC, PUSH_TIMEOUT_SEC, PUSH_TTL_SEC, now_kst, settings
from app.db import SessionLocal
from app.models import PushSubscription

log = logging.getLogger("app.push")

# 가족 알림 중 푸시로도 보내는 것 (FR-NT-003 일기·주간 이야기 + 11/19 마음 알림 2종). 나머지는 알림 목록에만
FAMILY_KINDS = ("DIARY_POSTED", "WEEKLY_READY", "MOOD_URGENT", "MOOD_LOW_2D")
# 푸시에는 어떤 알림이든 제목만 싣는다 — 마음 알림의 body 에는 어르신 이름과 '많이 힘드심·몸이 불편'이 들어 있어
# 잠금 화면을 보는 남에게 그대로 보인다 (11/19 보안 점검). 누구 이야기인지는 눌러서 앱 안 긴급 카드·알림 목록에서 본다
# 어르신 시간 알림 (FR-NT-002): 종류 → (폰에 뜨는 문장, 누르면 열리는 주소)
ELDER_PUSH = {
    "MEMORY_REMINDER": ("오늘의 한 장이 기다리고 있어요", "/elder/today"),  # 홈 위에 오늘의 한 장 팝업
    "DIARY_REMINDER": ("오늘 하루 이야기를 들려주세요", "/elder/diary"),  # 일기 시작 화면
}
# 가족 알림의 link_screen → 누르면 열리는 주소. 가족 홈은 그 어르신의 홈이 열리게 가족방 번호를 붙인다
# (화면 lib/push.ts 가 읽는다 — 알림 목록 NOTI_001 에서 눌렀을 때와 같게). 표에 없으면 앱 첫 주소
_FAMILY_URL = {"HOME_001": "/?room={room_id}", "WEEKLY_001": "/weekly/{room_id}"}

# 서버가 사용자가 준 주소로 POST 하게 되므로(SSRF) 알려진 푸시 서비스의 https 주소만 받고, 보낸다.
PUSH_HOSTS = ("fcm.googleapis.com", "updates.push.services.mozilla.com")  # 크롬·삼성 인터넷·엣지 / 파이어폭스
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com")  # 사파리(아이폰) / 윈도우 엣지
# 호스트는 소문자·숫자·점·하이픈만. 사용자 정보(@)·포트·역슬래시·# 가 낀 주소는 통째로 거절한다 —
# 주소 해석기마다 호스트를 다르게 읽을 틈을 두지 않는다
_ENDPOINT = re.compile(r"https://([a-z0-9.-]+)/[A-Za-z0-9._~%:/?=&+-]*", re.ASCII)

_RECORD_SIZE = 4096  # RFC 8291 4절 — 푸시 서비스가 받아 주는 본문 크기. 우리 본문은 1KB 안쪽
_QUEUED = "push_jobs"  # Session.info 의 칸 이름 — commit 을 기다리는 푸시들

# ponytail: 작업 스레드 2개·다시 보내기 없음 — 한 번에 수백 건을 보내게 되면(가족방이 많아지면) 줄이 밀린다. 그때 큐로
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push")
_http = httpx.Client(timeout=PUSH_TIMEOUT_SEC, follow_redirects=False)  # 다른 주소로 넘기는 응답은 따라가지 않는다


def _hide_push_url(record: logging.LogRecord) -> bool:
    """httpx 는 요청 주소를 INFO 로 남긴다 — 푸시 주소가 든 줄만 뺀다 (D15). 결과는 'push sub=… status=…' 줄에 있다."""
    args = record.args if isinstance(record.args, tuple) else ()
    return not any(isinstance(a, httpx.URL) and endpoint_allowed(str(a)) for a in args)


logging.getLogger("httpx").addFilter(_hide_push_url)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def enabled() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def _host(url: str) -> str | None:
    """허용된 푸시 서비스 주소면 그 호스트, 아니면 None."""
    m = _ENDPOINT.fullmatch(url)
    host = m[1] if m else ""
    return host if host in PUSH_HOSTS or host.endswith(PUSH_HOST_SUFFIXES) else None


def endpoint_allowed(url: str) -> bool:
    return _host(url) is not None


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(
    plaintext: bytes,
    ua_public: bytes,
    auth_secret: bytes,
    *,
    salt: bytes | None = None,
    as_private: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """RFC 8291 — 그 브라우저의 공개 키(p256dh)·인증 비밀(auth)로 암호화한 aes128gcm 본문 한 덩이.

    salt·as_private 는 평소 비워 둔다(보낼 때마다 새 난수·새 키). RFC 부록 A 의 값으로 정답을 대조하는 테스트만 넣는다.
    """
    salt = salt or os.urandom(16)
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    as_public = as_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    ecdh_secret = as_private.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    )
    # 3.3절: ECDH 비밀과 인증 비밀을 섞어 키 재료(IKM)로 → RFC 8188: 그 재료와 salt 로 내용 키(CEK)·nonce
    ikm = _hkdf(auth_secret, ecdh_secret, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    # 머리 86바이트 = salt 16 + 레코드 크기 4 + 키 길이 1 + 서버 임시 공개 키 65. 본문 끝 0x02 = 마지막(하나뿐인) 레코드
    header = salt + _RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)


def vapid(endpoint: str) -> str:
    """RFC 8292 — Authorization 헤더 값 'vapid t=<JWT>, k=<서버 공개 키>'. JWT 는 그 푸시 서비스(aud) 앞으로 12시간."""
    claims = {"aud": f"https://{_host(endpoint)}", "exp": int(now_kst().timestamp()) + PUSH_JWT_SEC}
    if settings.VAPID_SUBJECT:
        claims["sub"] = settings.VAPID_SUBJECT
    key = ec.derive_private_key(int.from_bytes(unb64u(settings.VAPID_PRIVATE_KEY), "big"), ec.SECP256R1())
    return f"vapid t={jwt.encode(claims, key, algorithm='ES256')}, k={settings.VAPID_PUBLIC_KEY.rstrip('=')}"


def _deliver(sub_id: int, endpoint: str, p256dh: str, auth: str, body: bytes, ttl: int, urgent: bool) -> None:
    """푸시 1건을 보낸다 (작업 스레드). 실패해도 다시 보내지 않는다 — 알림은 앱 안 목록에 이미 있다."""
    try:
        if not endpoint_allowed(endpoint):  # 받을 때 검사했지만 보내기 직전에 한 번 더
            raise ValueError("endpoint")
        r = _http.post(
            endpoint,
            content=encrypt(body, unb64u(p256dh), unb64u(auth)),
            headers={
                "Authorization": vapid(endpoint),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(ttl),
                "Urgency": "high" if urgent else "normal",
            },
        )
        if r.status_code in (404, 410):  # 푸시 서비스: '없는 구독'(앱 삭제·알림 끔·만료) → 그 줄을 지운다
            with SessionLocal() as db:
                db.execute(delete(PushSubscription).where(PushSubscription.subscription_id == sub_id))
                db.commit()
    except Exception as e:  # 망 오류·시간 초과·깨진 키. 예외 글에는 주소가 섞일 수 있어 종류만 (D15)
        log.warning("push failed sub=%s error=%s", sub_id, type(e).__name__)
        return
    log.info("push sub=%s status=%s", sub_id, r.status_code)


def _queue(db: Session, who, payload: dict, *, urgent: bool, ttl: int = PUSH_TTL_SEC) -> None:
    """조건(who)에 맞는 구독마다 푸시 1건을 예약한다. 스레드에는 ORM 객체가 아니라 값만 넘긴다."""
    if not enabled():
        return
    body = json.dumps(payload, ensure_ascii=False).encode()
    s = PushSubscription
    for row in db.execute(select(s.subscription_id, s.endpoint, s.p256dh, s.auth).where(who)):
        db.info.setdefault(_QUEUED, []).append((*row, body, ttl, urgent))


@event.listens_for(Session, "after_commit")
def _send_queued(session: Session) -> None:
    for job in session.info.pop(_QUEUED, ()):
        _pool.submit(_deliver, *job)


@event.listens_for(Session, "after_transaction_end")
def _drop_queued(session: Session, transaction) -> None:
    # commit 없이 끝난 작업(rollback·오류로 닫힘)의 푸시는 버린다. commit 된 것은 위에서 이미 꺼내 갔다
    if transaction.parent is None:
        session.info.pop(_QUEUED, None)


def queue_family(
    db: Session, user_ids: list[int], room_id: int, kind: str, title: str, body: str | None, link: str | None
) -> None:
    """가족 알림 1건을 그 가족들의 브라우저에 예약한다 — 푸시로 보내는 종류만 (routers/devices.notify_family 가 부른다).

    body 는 푸시에 넣지 않는다 — 일기 알림은 일기 글이고, 마음 알림은 어르신 이름과 상태가 들어 있다(잠금 화면).
    """
    if kind not in FAMILY_KINDS or not user_ids:
        return
    urgent = kind == "MOOD_URGENT"
    payload = {
        "title": title,
        "url": _FAMILY_URL.get(link or "", "/start").format(room_id=room_id),
        "tag": f"{kind}-{room_id}",
    }
    _queue(db, PushSubscription.user_id.in_(user_ids), payload, urgent=urgent)


def queue_elder(db: Session, room_id: int, kind: str) -> None:
    """어르신 기기에 시간 알림 1건을 예약한다 (services/scheduler 가 부른다, FR-NT-002).

    폰이 꺼져 있었으면 그날 자정까지만 전한다(다음 날 아침에 어제 알림이 뜨지 않게).
    """
    title, url = ELDER_PUSH[kind]
    now = now_kst()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    ttl = int((midnight - now).total_seconds())
    _queue(db, PushSubscription.room_id == room_id, {"title": title, "url": url, "tag": kind}, urgent=False, ttl=ttl)


def forget_room(db: Session, room_id: int) -> None:
    """기기 연결 해제·새 기기 연결 — 그 가족방의 옛 어르신 기기 구독을 지운다 (commit 은 부른 쪽이)."""
    db.execute(delete(PushSubscription).where(PushSubscription.room_id == room_id))
