#!/usr/bin/env bash
# 서버 저장소에서: bash deploy/check.sh
set -uo pipefail
export TZ=KST-9

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || exit 1
cd -- "$repo_dir" || exit 1
warnings=0
warn() {
    printf '주의: %s\n' "$1"
    (( warnings += 1 ))
}

if disk="$(df -h /)"; then
    printf '%s\n' "$disk"
    usage="$(awk 'NR == 2 { sub(/%/, "", $5); print $5 }' <<< "$disk")"
    if [[ "$usage" =~ ^[0-9]+$ ]] && (( usage > 80 )); then
        warn '루트 디스크 사용률이 80%를 넘었어요.'
    fi
else
    warn '디스크 사용량을 확인하지 못했어요.'
fi
free -m || warn '메모리와 스왑을 확인하지 못했어요.'
docker compose --profile deploy ps || warn '컨테이너 상태를 확인하지 못했어요.'

if ! timeout 10s docker compose exec -T api python -c '
import json
from urllib.request import urlopen
with urlopen("http://127.0.0.1:8000/api/health", timeout=5) as response:
    health = json.load(response)
print("API / DB:", health.get("ok"), health.get("db"))
raise SystemExit(0 if health.get("ok") is True and health.get("db") is True else 1)
'; then
    warn 'API 또는 DB 상태를 확인해 주세요.'
fi

backup_dir="${BACKUP_DIR:-"$HOME/only-backups"}"
latest=''
latest_at=0
shopt -s nullglob
for backup in "$backup_dir"/only_app_*.sql.gz; do
    [[ -f "$backup" ]] || continue
    modified="$(stat -c %Y -- "$backup")" || continue
    if (( modified > latest_at )); then
        latest="$backup"
        latest_at="$modified"
    fi
done
if [[ -n "$latest" ]]; then
    printf '마지막 백업: %s\n' "$(stat -c '%n · %s bytes · %y' -- "$latest")"
    if (( $(date +%s) - latest_at > 86400 )); then
        warn '마지막 백업이 24시간 넘었어요.'
    fi
else
    warn '백업 파일을 찾지 못했어요.'
fi
if ! crontab -l 2>/dev/null | grep -F 'db/backup.sh'; then
    warn 'crontab에 백업 줄이 없거나 읽을 수 없어요.'
fi
if domain="$(docker compose exec -T caddy printenv DOMAIN)" && [[ -n "$domain" ]] &&
    certificate="$(timeout 10s openssl s_client -connect localhost:443 -servername "$domain" </dev/null 2>/dev/null |
        openssl x509 -noout -enddate 2>/dev/null)"; then
    printf '인증서 만료일: %s\n' "$certificate"
else
    warn '인증서 만료일을 확인하지 못했어요.'
fi
git log -1 --oneline || warn '현재 커밋을 확인하지 못했어요.'
printf '주의 %d개\n' "$warnings"
