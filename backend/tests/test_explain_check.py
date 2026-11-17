"""인덱스 점검의 배포 차단과 관리 연결 대상을 확인한다."""

import sys

import pytest

from scripts import explain_check


def test_deploy_is_rejected_before_database_access(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "deploy")
    monkeypatch.setattr(sys, "argv", ["explain_check"])
    monkeypatch.setattr(explain_check, "admin_engine", lambda url: pytest.fail("배포 차단 전에 DB를 열면 안 됩니다"))
    assert explain_check.main() == 1
    assert "배포 서버에서는" in capsys.readouterr().out


def test_admin_connection_targets_postgres_and_rejects_test_database(monkeypatch):
    calls = []
    monkeypatch.setattr(explain_check, "create_engine", lambda url, **kwargs: calls.append((url, kwargs)))
    explain_check.admin_engine("postgresql+psycopg://only:only@localhost/only_app")
    assert calls[0][0].database == "postgres"
    assert calls[0][1]["isolation_level"] == "AUTOCOMMIT"
    for url in ("sqlite:///only_app", "postgresql+psycopg://only:only@localhost/only_app_explain"):
        with pytest.raises(ValueError):
            explain_check.admin_engine(url)
    assert len(calls) == 1
