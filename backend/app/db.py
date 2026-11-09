"""동기 SQLAlchemy 2.0 (D3). 접속마다 timezone=Asia/Seoul 고정 (D12)."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    hide_parameters=True,  # DB 오류 메시지에 SQL 파라미터(어르신 말·토큰 해시)를 넣지 않는다 (D15)
    connect_args={"options": "-c timezone=Asia/Seoul"},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
