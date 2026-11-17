"""표준 입력의 DB 백업을 R2에 한 벌 더 보관한다. 보관 기간은 업로드 시각부터 7일."""

import argparse
import re
import sys
from datetime import timedelta

from app.config import now_kst, settings
from app.services.storage import _R2

BACKUP_NAME = re.compile(r"only_app_[0-9]{8}_[0-9]{4}_[A-Za-z0-9_-]+\.sql\.gz")


def upload(name: str, data: bytes) -> None:
    """업로드가 성공한 뒤에만 7일이 지난 백업을 정리한다."""
    if not BACKUP_NAME.fullmatch(name):
        raise ValueError("백업 파일 이름은 only_app_날짜_시각_구분.sql.gz 모양이어야 해요")
    if not data:
        raise ValueError("빈 백업은 올릴 수 없어요")
    backend = _R2()
    backend.put(f"backups/{name}", data, "application/gzip")
    cutoff = now_kst() - timedelta(days=7)
    for key, uploaded_at in backend.list("backups/"):
        if BACKUP_NAME.fullmatch(key.removeprefix("backups/")) and uploaded_at < cutoff:
            backend.delete(key)
    print("R2 백업 완료")


def main() -> None:
    parser = argparse.ArgumentParser(description="표준 입력의 DB 백업을 R2에 7일 보관합니다.")
    parser.add_argument("filename")
    args = parser.parse_args()
    if settings.STORAGE != "r2":
        print("로컬 저장소라 건너뜀")
        return
    if not BACKUP_NAME.fullmatch(args.filename):
        parser.error("백업 파일 이름은 only_app_날짜_시각_구분.sql.gz 모양이어야 해요")
    upload(args.filename, sys.stdin.buffer.read())


if __name__ == "__main__":
    main()
