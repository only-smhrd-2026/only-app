"""운영자가 가족 계정의 비밀번호를 다시 정한다 — 메일을 보내지 않아 '비밀번호 찾기'가 없다 (11/18 실사용).

서버에서: docker compose exec api python -m scripts.set_password <이메일>
새 비밀번호는 실행한 뒤 화면에 보이지 않게 두 번 묻는다. 셸 기록·ps 에 남으니 명령줄 인자·환경 변수로는 받지 않는다.
맥에서 ssh 한 줄로 돌릴 때는 ssh 에 -t 를 붙인다 — 터미널이 없으면 입력한 글자를 가리지 못한다(경고가 나온다).
규칙은 가입·비밀번호 바꾸기와 같다 (schemas.auth.NewPassword).

바꿔도 그대로인 것:
- 이미 로그인된 기기는 쿠키가 만료될 때(config.SESSION_COOKIE_DAYS 일)까지 로그인된 채다. 끊는 장치는 아직 없다.
- 여러 번 틀려 로그인이 막혀 있었다면 막힌 때부터 config.LOGIN_FAIL_WINDOW_SEC 초 뒤에 풀린다.
  그 셈은 서버 프로세스 메모리에 있어, 따로 도는 이 스크립트가 지울 수 없다.
"""

import argparse
import getpass
import re

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import User
from app.schemas.auth import EMAIL_RE, NewPassword
from app.security import hash_password


def clean_email(raw: str) -> str:
    """가입 때와 같은 모양·길이에 더해 ASCII 만 받는다 — 터미널이 한글 입력 상태라 자모가 섞이는 실수를 막는다."""
    # 소문자로 바꾸기 전에 본다: 켈빈 기호(U+212A)처럼 lower() 가 ASCII 'k' 로 바꿔 버리는 글자가 있다
    if not raw.isascii() or len(raw) > 255 or not re.fullmatch(EMAIL_RE, raw):
        raise ValueError("이메일을 다시 확인해 주세요 (한글이 섞이지 않았는지, name@example.com 모양인지)")
    return raw.lower()


def read_password() -> tuple[str, str]:
    """새 비밀번호를 화면에 보이지 않게 두 번 받는다. 터미널 없이 돌리는 테스트는 이 함수를 바꿔 끼운다."""
    return getpass.getpass("새 비밀번호: "), getpass.getpass("한 번 더: ")


def check_password(first: str, second: str) -> str:
    if first != second:
        raise ValueError("두 번 입력한 비밀번호가 서로 달라요")
    try:
        return TypeAdapter(NewPassword).validate_python(first)
    except ValidationError:
        # pydantic 오류 글에는 입력값이 들어 있다 — 비밀번호가 화면에 찍히지 않게 문장을 새로 쓴다
        raise ValueError("비밀번호는 8~64자, 72바이트(한글만 쓰면 24자)까지 쓸 수 있어요") from None


def find_user(db: Session, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email, User.status == "ACTIVE"))
    if user is None:
        raise ValueError("계정을 찾을 수 없어요")
    return user


def main() -> None:
    parser = argparse.ArgumentParser(
        description="가족 계정의 비밀번호를 다시 정합니다. 새 비밀번호는 실행한 뒤에 묻습니다."
    )
    parser.add_argument("email")
    args = parser.parse_args()
    try:
        email = clean_email(args.email)
        # 비밀번호를 묻기 전에 계정부터 본다. 입력을 기다리는 동안 DB 를 잡아 두지 않게 바로 닫는다
        with SessionLocal() as db:
            find_user(db, email)
        password = check_password(*read_password())
        with SessionLocal() as db:
            user = find_user(db, email)
            user.password_hash = hash_password(password)
            db.commit()
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    print(f"user_id {user.user_id}: 비밀번호를 바꿨어요")


if __name__ == "__main__":
    main()
