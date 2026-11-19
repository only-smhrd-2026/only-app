"""운영자용 비밀번호 다시 정하기: 바뀌는 경우·안 바뀌는 경우, 출력에 비밀번호·해시가 없는지 확인한다."""

import sys

import pytest

from app.db import SessionLocal
from app.models import User
from scripts import set_password
from tests.conftest import signup

OLD = "test1234"  # conftest.signup 의 비밀번호
NEW = "new-pass-5678"


def run(monkeypatch, email: str, typed: tuple[str, str] | None = (NEW, NEW)) -> int:
    """스크립트를 명령줄처럼 돌리고 종료 코드를 돌려준다(성공 0). typed=None 이면 비밀번호를 물어보는 순간 실패."""
    monkeypatch.setattr(sys, "argv", ["set_password", email])
    ask = (lambda: typed) if typed else (lambda: pytest.fail("비밀번호를 물어보면 안 됩니다"))
    monkeypatch.setattr(set_password, "read_password", ask)
    try:
        set_password.main()
    except SystemExit as exc:
        return exc.code
    return 0


def stored_hash(user_id: int) -> str:
    with SessionLocal() as db:
        return db.get(User, user_id).password_hash


def login(client, email: str, password: str) -> int:
    return client.post("/api/auth/login", json={"email": email, "password": password}).status_code


def test_new_password_replaces_old_and_output_has_no_secret(client, monkeypatch, capsys):
    user = signup(client)
    old_hash = stored_hash(user["user_id"])
    monkeypatch.setattr(sys, "argv", ["set_password", user["email"].upper()])  # 대문자로 쳐도 같은 계정
    prompts = []
    monkeypatch.setattr(set_password.getpass, "getpass", lambda prompt: prompts.append(prompt) or NEW)
    set_password.main()
    captured = capsys.readouterr()
    assert captured.out == f"user_id {user['user_id']}: 비밀번호를 바꿨어요\n" and captured.err == ""
    assert len(prompts) == 2  # 화면에 보이지 않는 입력(getpass)으로 두 번
    new_hash = stored_hash(user["user_id"])
    assert new_hash != old_hash and new_hash.startswith("$2b$10$")  # security.hash_password 와 같은 모양
    for secret in (NEW, old_hash, new_hash):
        assert secret not in captured.out + captured.err
    assert login(client, user["email"], NEW) == 200
    assert login(client, user["email"], OLD) == 401


@pytest.mark.parametrize(
    "typed",
    [
        (NEW, NEW + "!"),  # 두 번 입력이 다름
        ("short12", "short12"),  # 8자 미만
        ("x" * 65, "x" * 65),  # 64자 초과
        ("가" * 25, "가" * 25),  # bcrypt 72바이트 초과 (가입·비밀번호 바꾸기와 같은 규칙)
    ],
)
def test_mismatch_or_rule_violation_changes_nothing(client, monkeypatch, capsys, typed):
    user = signup(client)
    old_hash = stored_hash(user["user_id"])
    assert run(monkeypatch, user["email"], typed) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "비밀번호" in captured.err
    assert typed[0] not in captured.err and typed[1] not in captured.err  # 입력한 비밀번호를 되찍지 않는다
    assert stored_hash(user["user_id"]) == old_hash
    assert login(client, user["email"], OLD) == 200


def test_unknown_or_withdrawn_account_exits_before_asking(client, monkeypatch, capsys):
    user = signup(client)
    with SessionLocal() as db:
        db.get(User, user["user_id"]).status = "WITHDRAWN"
        db.commit()
    old_hash = stored_hash(user["user_id"])
    for email in ("nobody@test.local", user["email"]):
        assert run(monkeypatch, email, typed=None) == 1
        captured = capsys.readouterr()
        assert captured.out == "" and captured.err == "계정을 찾을 수 없어요\n"
    assert stored_hash(user["user_id"]) == old_hash


@pytest.mark.parametrize(
    "email",
    [
        "ㅁtester@test.local",  # 한글 입력 상태에서 섞여 들어온 자모
        "tester@test.localㅇ",
        "테스터@test.local",
        "Kim@test.local",  # 켈빈 기호 — lower() 뒤에는 ASCII 'k' 가 된다
        "tester.test.local",  # @ 없음
        "tester@local",  # 점 없음
        "a" * 250 + "@test.local",  # 255자 초과
    ],
)
def test_bad_email_is_rejected_before_database(monkeypatch, capsys, email):
    monkeypatch.setattr(set_password, "SessionLocal", lambda: pytest.fail("이메일 검사 전에 DB를 열면 안 됩니다"))
    assert run(monkeypatch, email, typed=None) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "이메일을 다시 확인" in captured.err
