#!/usr/bin/env bash
# 매일 04:00 (서버 시간대 Asia/Seoul) crontab 예:
# 0 4 * * * cd /home/ubuntu/only-app && bash db/backup.sh >> /home/ubuntu/only-backup.log 2>&1
# 복원은 빈 DB에만 (먼저 별도 시험 DB에서 확인):
# gunzip -c /경로/only_app_날짜_시각_구분.sql.gz | docker compose exec -T db psql -v ON_ERROR_STOP=1 -U only only_app
# 백업에는 대화·사진 설명 등 개인정보가 있다. GitHub·Drive에 올리지 않는다.
# 기본 폴더: $HOME/only-backups. BACKUP_DIR로 저장소 밖의 다른 폴더를 지정할 수 있다.
# 같은 분에 두 번 실행해도 덮어쓰지 않도록 날짜·시각 뒤에 임의 구분자를 붙인다.

set -euo pipefail
umask 077
# POSIX KST(UTC+9)는 zoneinfo가 없는 Windows Git Bash에서도 한국 시각으로 동작한다.
export TZ=KST-9

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
backup_dir="${BACKUP_DIR:-"$HOME/only-backups"}"
mkdir -p -- "$backup_dir"
backup_dir="$(cd -- "$backup_dir" && pwd -P)"
if [[ "$backup_dir" == / || "$backup_dir" == "$repo_dir" || "$backup_dir" == "$repo_dir/"* ]]; then
    printf '백업 폴더는 저장소 밖의 전용 폴더여야 합니다.\n' >&2
    exit 1
fi
chmod 700 -- "$backup_dir"
cd -- "$repo_dir"

temporary=""
cleanup() {
    if [[ -n "$temporary" && -f "$temporary" ]]; then
        rm -f -- "$temporary"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

stamp="$(date +%Y%m%d_%H%M)"
temporary="$(mktemp "$backup_dir/.only_app_${stamp}_XXXXXX")"
chmod 600 -- "$temporary"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$temporary"
gzip -t -- "$temporary"
temporary_name="${temporary##*/}"
final="$backup_dir/${temporary_name#.}.sql.gz"
mv -n -- "$temporary" "$final"
if [[ -e "$temporary" ]]; then
    printf '백업 파일 이름이 겹쳐 저장하지 않았습니다.\n' >&2
    exit 1
fi
temporary=""

# 이 스크립트의 이름 규칙을 따르는 일반 파일만, 7일(10080분)을 넘었을 때 정리한다.
find "$backup_dir" -maxdepth 1 -type f \
    -name 'only_app_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9]_*.sql.gz' \
    -mmin +10080 -delete
printf '백업 완료: %s\n' "$final"

if [[ "${BACKUP_R2:-0}" == 1 ]]; then
    docker compose exec -T api uv run python -m scripts.backup_to_r2 "${final##*/}" < "$final"
fi
