"""시간대 Asia/Seoul 1곳 고정 (D12). 서버·DB 세션 둘 다 확인."""

from datetime import date

from sqlalchemy import text

from app.config import TZ, now_kst, today_kst
from app.db import engine


def test_config_tz():
    assert str(TZ) == "Asia/Seoul"
    assert now_kst().utcoffset().total_seconds() == 9 * 3600
    assert isinstance(today_kst(), date)


def test_db_session_tz():
    with engine.connect() as conn:
        assert conn.execute(text("SHOW timezone")).scalar() == "Asia/Seoul"
        db_today = conn.execute(text("SELECT (now() AT TIME ZONE 'Asia/Seoul')::date")).scalar()
        assert db_today == today_kst()
