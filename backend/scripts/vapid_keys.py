"""웹 푸시용 VAPID 키 쌍을 새로 만들어 한 번 보여 준다. backend 폴더에서:  uv run python -m scripts.vapid_keys

나온 세 줄을 서버 .env 에 붙이고(VAPID_SUBJECT 는 운영자 주소로 고쳐서) 다시 배포한다.
개인 키는 이 출력에만 있다 — 단톡방·이슈·PR 에 붙이지 않는다.
키를 바꾸면 전에 알림을 켠 폰의 구독은 못 쓰게 된다(화면이 다음에 열릴 때 새 키로 다시 구독한다).
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.services.push import b64u


def generate() -> tuple[str, str]:
    """(공개 키 65바이트, 개인 키 32바이트)를 base64url 글자로."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64u(public), b64u(key.private_numbers().private_value.to_bytes(32, "big"))


if __name__ == "__main__":
    public, private = generate()
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
    print("VAPID_SUBJECT=mailto:운영자-메일-주소로-바꾸세요")
