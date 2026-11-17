"""백업 사진 주소 차단·로컬 건너뛰기·R2 보관 기간과 페이지 처리."""

import sys
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.config import now_kst
from app.services.storage import _R2
from scripts import backup_to_r2
from tests.conftest import setup_elder

NAME = "only_app_20261117_0400_abcdef.sql.gz"


def test_backup_cannot_be_read_as_photo(client):
    setup_elder(client)
    assert client.get(f"/api/media/backups/{NAME}").status_code == 404


def test_local_storage_skips_without_reading_stdin(monkeypatch, capsys):
    monkeypatch.setattr(backup_to_r2.settings, "STORAGE", "local")
    monkeypatch.setattr(sys, "argv", ["backup_to_r2", NAME])
    backup_to_r2.main()
    assert capsys.readouterr().out.strip() == "로컬 저장소라 건너뜀"


def test_upload_then_delete_only_backups_older_than_seven_days(monkeypatch):
    now = now_kst()
    events = []
    old = "backups/only_app_20261109_0400_old.sql.gz"
    boundary = "backups/only_app_20261110_0400_keep.sql.gz"
    backend = SimpleNamespace(
        put=lambda *args: events.append(("put", args)),
        list=lambda prefix: [
            (old, now - timedelta(days=8)),
            (boundary, now - timedelta(days=7)),
            ("backups/other.sql.gz", now - timedelta(days=8)),
            (f"backups/{NAME}", now),
        ],
        delete=lambda key: events.append(("delete", key)),
    )
    monkeypatch.setattr(backup_to_r2, "_R2", lambda: backend)
    monkeypatch.setattr(backup_to_r2, "now_kst", lambda: now)
    backup_to_r2.upload(NAME, b"gzip-backup")
    assert events == [("put", (f"backups/{NAME}", b"gzip-backup", "application/gzip")), ("delete", old)]
    for name in ("../escape.sql.gz", "other.sql.gz", "only_app_bad.sql.gz"):
        with pytest.raises(ValueError):
            backup_to_r2.upload(name, b"backup")


def test_r2_list_reads_every_page():
    now = now_kst()

    class Paginator:
        def paginate(self, **kwargs):
            assert kwargs == {"Bucket": "test", "Prefix": "backups/"}
            return [
                {"Contents": [{"Key": "backups/one", "LastModified": now}]},
                {},
                {"Contents": [{"Key": "backups/two", "LastModified": now}]},
            ]

    backend = _R2.__new__(_R2)
    backend.bucket = "test"
    backend.client = SimpleNamespace(get_paginator=lambda operation: Paginator())
    assert list(backend.list("backups/")) == [("backups/one", now), ("backups/two", now)]
