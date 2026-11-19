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
