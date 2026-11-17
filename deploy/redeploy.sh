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
previous_commit="$(git rev-parse HEAD)"
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
if ! git diff --quiet "$previous_commit" HEAD -- Caddyfile; then
    docker compose --profile deploy restart caddy
fi

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
if [[ -d frontend/dist/assets ]]; then
    find frontend/dist/assets -maxdepth 1 -type f -name 'index-*.js' -printf '%f\n'
else
    docker compose exec -T caddy sh -c 'for asset in /srv/assets/index-*.js; do
        [ -f "$asset" ] || exit 1
        basename "$asset"
    done'
fi
