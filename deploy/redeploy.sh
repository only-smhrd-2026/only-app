#!/usr/bin/env bash
# 서버 저장소에서: bash deploy/redeploy.sh [db/migrations/파일.sql ...]
# 맥에서: ssh -i <키> <서버> 'cd ~/only-app && bash deploy/redeploy.sh db/migrations/….sql'
# 마이그레이션은 사람이 고른, 두 번 실행해도 안전한 파일만 전달한다 (D57).
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$repo_dir"
if [[ "$(git branch --show-current)" != develop ]]; then
    printf 'develop 브랜치에서만 배포할 수 있어요.\n' >&2
    exit 1
fi
git pull --ff-only origin develop

# 인자를 전부 검사한 뒤 적용한다. 중간의 잘못된 경로 때문에 일부만 적용되는 것을 막는다.
migrations=()
for migration in "$@"; do
    case "$migration" in
        db/migrations/*.sql) ;;
        *) printf 'db/migrations/ 안의 .sql 파일만 지정해 주세요.\n' >&2; exit 1 ;;
    esac
    migration_path="$(realpath -e -- "$migration")"
    if [[ "$migration_path" != "$repo_dir/db/migrations/"*.sql || ! -f "$migration_path" ]]; then
        printf '마이그레이션 경로가 허용된 폴더 밖이거나 파일이 아니에요.\n' >&2
        exit 1
    fi
    migrations+=("$migration_path")
done

bash db/backup.sh
for migration in "${migrations[@]}"; do
    docker compose exec -T db sh -c \
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < "$migration"
done

docker compose --profile deploy up -d --build
docker image prune -f
# Caddyfile 은 파일로 마운트돼 caddy 가 새로 만들어지지 않으면 옛 내용을 쥐고 있다 → 매번 다시 읽게 한다(1초 안팎).
# '바뀌었을 때만'이면 pull 뒤 다른 단계가 실패해 다시 돌릴 때 바뀐 Caddyfile 이 빠진다
docker compose --profile deploy restart caddy

deadline=$((SECONDS + 90))
healthy=0
while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    if timeout "${remaining}s" docker compose exec -T api python -c '
import json
import sys
from urllib.request import urlopen

try:
    with urlopen("http://127.0.0.1:8000/api/health", timeout=min(5, int(sys.argv[1]))) as response:
        health = json.load(response)
    sys.exit(0 if health.get("ok") is True and health.get("db", True) is True else 1)
except Exception:
    sys.exit(1)
' "$remaining"; then
        healthy=1
        break
    fi
    remaining=$((deadline - SECONDS))
    (( remaining <= 0 )) || sleep "$((remaining < 2 ? remaining : 2))"
done
if [[ "$healthy" != 1 ]]; then
    printf '90초 안에 API와 DB 상태를 확인하지 못했어요. 배포 상태를 확인해 주세요.\n' >&2
    exit 1
fi

hour=19
if [[ "$(date +%z)" == +0900 ]]; then
    hour=4
fi
printf -v cron_repo '%q' "$repo_dir"
printf -v cron_log '%q' "$HOME/only-backup.log"
backup_command='bash db/backup.sh'
# R2 사본을 한 번 켰으면 다음 배포에서 BACKUP_R2 를 빠뜨려도 조용히 꺼지지 않게 지금 cron 줄을 본다(끄려면 BACKUP_R2=0)
if [[ -z "${BACKUP_R2:-}" ]] && { crontab -l 2>/dev/null || true; } | grep -q 'BACKUP_R2=1 bash db/backup.sh'; then
    BACKUP_R2=1
fi
if [[ "${BACKUP_R2:-0}" == 1 ]]; then
    backup_command="BACKUP_R2=1 $backup_command"
fi
cron_command="cd $cron_repo && $backup_command >> $cron_log 2>&1"
cron_command="${cron_command//%/\\%}"
{
    { crontab -l 2>/dev/null || true; } | grep -vF 'db/backup.sh' || true
    printf '0 %s * * * %s # only-app daily backup\n' "$hour" "$cron_command"
} | crontab -

git log -1 --oneline
docker compose --profile deploy ps
# 화면은 다단계 Docker 빌드로 Caddy 이미지의 /srv에 들어간다.
docker compose exec -T caddy sh -c 'for asset in /srv/assets/index-*.js; do
    [ -f "$asset" ] || exit 1
    basename "$asset"
done'
