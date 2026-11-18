#!/usr/bin/env bash
# 시험 복원: bash db/restore.sh 백업파일.sql.gz [--keep]
# 실제 복구는 서버를 멈추고 빈 DB를 만든 뒤 백업을 풀어 넣는다.
# 이 스크립트의 복원·삭제 대상은 only_app_restore_test로 고정한다.
# 다른 DB나 서버 설정을 건드리는 명령이 포함된 백업은 중단한다.
set -euo pipefail
export TZ=KST-9
umask 077

if [[ $# -lt 1 || $# -gt 2 || ( $# -eq 2 && "$2" != --keep ) ]]; then
    printf '사용법: bash db/restore.sh 백업파일.sql.gz [--keep]\n' >&2
    exit 1
fi
backup_file="$1"
keep="${2:-}"
test_db=only_app_restore_test
[[ -f "$backup_file" ]] || { printf '백업 파일을 찾을 수 없어요.\n' >&2; exit 1; }
gzip -t -- "$backup_file"
# psql 메타 명령(\c·\!·\g |…·\o |… 등)은 아래 풀어 넣기에서 \restrict 로 통째로 막는다(11/18 다듬기).
# 여기서는 SQL 만 본다 — COPY 자료 줄(가족·어르신이 쓴 글)은 빼고, /* */ 주석을 지운 뒤 다른 DB·서버를 건드리는 문장을 찾는다
# (자료 줄을 보면 'TV program' 같은 글에도 멈췄다).
blocked_sql='(CREATE|DROP|ALTER)[[:space:]]+DATABASE|ALTER[[:space:]]+SYSTEM|PROGRAM'
# grep 은 끝까지 읽어 pipefail 에서 gzip 의 SIGPIPE 를 피한다.
if gzip -dc -- "$backup_file" | awk '
    copying { if ($0 == "\\.") copying = 0; next }
    /^COPY .* FROM stdin;$/ { copying = 1; next }
    { gsub(/\/\*([^*]|\*+[^*\/])*\*+\//, " "); print }' | grep -Ei -- "$blocked_sql" > /dev/null; then
    printf '이 백업에는 다른 DB 를 건드리는 줄이 있어 되살리지 않았어요\n' >&2
    exit 1
else
    scan_status=("${PIPESTATUS[@]}")
    if [[ "${scan_status[0]}" -ne 0 || "${scan_status[1]}" -ne 0 || "${scan_status[2]}" -ne 1 ]]; then
        printf '백업 내용을 검사할 수 없어 되살리지 않았어요\n' >&2
        exit 1
    fi
fi
backup_file="$(cd -- "$(dirname -- "$backup_file")" && pwd -P)/$(basename -- "$backup_file")"
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$repo_dir"

# 설정 실수로 운영 DB 이름이 시험 DB와 같으면 삭제하기 전에 중단한다.
production_db="$(docker compose exec -T db sh -c 'printf "%s" "$POSTGRES_DB"')"
if [[ -z "$production_db" || "$production_db" == "$test_db" ]]; then
    printf '운영 DB와 시험 DB를 구분할 수 없어 중단했어요.\n' >&2
    exit 1
fi

report_dir="$(mktemp -d)"
created=0
cleanup() {
    result=$?
    trap - EXIT
    if [[ "$created" == 1 && "$keep" != --keep ]]; then
        docker compose exec -T db sh -c 'dropdb --if-exists -U "$POSTGRES_USER" only_app_restore_test' || result=1
    fi
    rm -f -- "$report_dir/production" "$report_dir/restored"
    rmdir -- "$report_dir"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker compose exec -T db sh -c 'dropdb --if-exists -U "$POSTGRES_USER" only_app_restore_test'
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" only_app_restore_test'
created=1
# 맨 앞에 이 스크립트만 아는 난수 키로 \restrict — 그 뒤로 psql 은 백업 안의 모든 \ 명령을 거부하고 멈춘다(ON_ERROR_STOP).
# pg_dump 가 넣은 \restrict·\unrestrict 줄은 빼고 우리 키로 다시 건다
restrict_key="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
{
    printf '\\restrict %s\n' "$restrict_key"
    gunzip -c -- "$backup_file" | grep -Ev '^\\(un)?restrict([[:space:]]|$)'
} | docker compose exec -T db sh -c \
    'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" only_app_restore_test' > /dev/null

counts() {
    docker compose exec -T db sh -c 'psql -X -qAt -v ON_ERROR_STOP=1 -F "|" -U "$POSTGRES_USER" "$1"' sh "$1" <<'SQL'
SELECT format('SELECT %L, count(*) FROM %I.%I', schemaname || '.' || tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname NOT LIKE 'pg_%' AND schemaname <> 'information_schema'
ORDER BY schemaname, tablename
\gexec
SQL
}
counts "$production_db" > "$report_dir/production"
counts "$test_db" > "$report_dir/restored"
declare -A production restored
while IFS='|' read -r table count; do
    [[ -z "$table" ]] || production["$table"]="$count"
done < "$report_dir/production"
while IFS='|' read -r table count; do
    [[ -z "$table" ]] || restored["$table"]="$count"
done < "$report_dir/restored"
printf '%-45s %12s %12s\n' '테이블' '운영 DB' '시험 DB'
while IFS= read -r table; do
    [[ -z "$table" ]] || printf '%-45s %12s %12s\n' "$table" "${production[$table]:-없음}" "${restored[$table]:-없음}"
done < <(printf '%s\n' "${!production[@]}" "${!restored[@]}" | sort -u)
if ! diff -q <(sort "$report_dir/production") <(sort "$report_dir/restored") > /dev/null; then
    printf '행 수가 달라요. 백업 뒤 운영 데이터가 바뀌었는지도 확인해 주세요.\n' >&2
    exit 1
fi
