"""배포 서버용 ALTER 파일(db/migrations/*.sql)은 전부, 이미 최신 모양인 DB 에 두 번 돌려도 오류가 없어야 한다.

deploy/redeploy.sh 가 인자로 받은 파일을 그대로 돌린다 — 오타 하나로 배포가 멈추지 않게.
"""

import pytest

from app.config import ROOT
from app.db import engine

FILES = sorted((ROOT / "db" / "migrations").glob("*.sql"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_migration_runs_twice(client, path):
    sql = path.read_text("utf-8")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(sql)
        conn.exec_driver_sql(sql)


SHAPE = """
SELECT 'col', table_name || '.' || column_name || ' ' || data_type || ' ' || is_nullable || ' '
       || coalesce(column_default, '')
FROM information_schema.columns WHERE table_schema = 'public'
UNION ALL
SELECT 'con', conrelid::regclass::text || ' ' || conname || ' ' || pg_get_constraintdef(oid)
FROM pg_constraint WHERE connamespace = 'public'::regnamespace
ORDER BY 1, 2
"""


def test_all_migrations_in_order_keep_schema_sql_shape(client):
    """서버처럼 모든 ALTER 파일을 차례로(두 번씩) 돌린 뒤에도 칸·제약이 schema.sql 로 만든 모양과 같다 (11/23).

    옛 파일이 되돌린 제약(예: 1113 의 알림 종류)은 뒤 파일이 다시 새 모양으로 돌려놓아야 한다.
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        before = conn.exec_driver_sql(SHAPE).all()
        for path in FILES:
            conn.exec_driver_sql(path.read_text("utf-8"))
            conn.exec_driver_sql(path.read_text("utf-8"))
        assert conn.exec_driver_sql(SHAPE).all() == before
