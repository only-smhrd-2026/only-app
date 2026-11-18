#!/usr/bin/env bash
# 서버 저장소에서: bash deploy/rollback.sh <커밋>
# 맥에서: ssh -i <키> <서버> 'cd ~/only-app && bash deploy/rollback.sh <커밋>'
# DB 마이그레이션을 되돌려야 하면 이번 백업과 db/restore.sh를 참고해 사람이 판단한다.
# 최신 버전으로 가려면: bash deploy/redeploy.sh
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$repo_dir"

if (( $# != 1 )); then
    printf '사용법: bash deploy/rollback.sh <커밋>\n' >&2
    git log --oneline -10
    exit 1
fi
if [[ "$(git branch --show-current)" != develop ]]; then
    printf 'develop 브랜치에서만 되돌릴 수 있어요.\n' >&2
    exit 1
fi
git fetch origin develop
if ! target="$(git rev-parse --verify --end-of-options "$1^{commit}")" ||
    ! git merge-base --is-ancestor "$target" origin/develop; then
    printf 'origin/develop에 포함된 커밋을 지정해 주세요.\n' >&2
    exit 1
fi
if ! git diff --quiet HEAD --; then
    printf '저장소의 변경사항을 정리한 뒤 되돌려 주세요.\n' >&2
    exit 1
fi
previous="$(git rev-parse HEAD)"
printf '현재 커밋: %s\n' "$previous"
bash db/backup.sh
git reset --hard "$target"
docker compose --profile deploy up -d --build
# Caddyfile은 마운트된 파일이다. 같은 커밋으로 재시도해도 다시 읽게 한다.
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
    printf '90초 안에 API와 DB 상태를 확인하지 못했어요. 되돌린 버전의 배포 상태를 확인해 주세요.\n' >&2
    exit 1
fi
