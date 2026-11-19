"""웹 푸시 구독 요청·응답 모양. 구독 요청은 브라우저의 PushSubscription.toJSON() 을 그대로 받는다."""

from pydantic import BaseModel, Field


class PushKeysIn(BaseModel):
    # base64url 글자만, 길이까지 맞아야 한다(끝의 = 는 있어도 됨). 풀면 65바이트(0x04 로 시작 = 'B')·16바이트
    p256dh: str = Field(pattern=r"^B[A-Za-z0-9_-]{86}=?$")  # 브라우저 공개 키 (P-256 점)
    auth: str = Field(pattern=r"^[A-Za-z0-9_-]{22}(==)?$")  # 브라우저 인증 비밀


class PushSubscribeIn(BaseModel):
    # 허용된 푸시 서비스 주소인지는 routers/push.py 가 본다(아니면 400). 여기서는 길이만 — DB 칸 VARCHAR(1000)
    endpoint: str = Field(min_length=1, max_length=1000)
    keys: PushKeysIn


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)


class PushKeyOut(BaseModel):
    public_key: str | None  # 서버 VAPID 공개 키(base64url). null = 이 서버는 푸시를 안 쓴다 → 화면이 알림 카드를 숨긴다
