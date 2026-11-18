"""요청 시간 요약.

docker compose logs --no-color --since 24h api | docker compose exec -T api python -m scripts.latency_report
"""

import argparse
import re
import sys
from collections import defaultdict
from math import ceil
from statistics import median

REQUEST = re.compile(r"(?:^|\s)req method=\S+ route=(\S+) status=([1-5]\d{2}) ms=(\d+)\s*$")


def summarize(samples):
    times = sorted(ms for _, ms in samples)
    if not times:
        return 0, 0, 0, 0, 0
    # p95 는 nearest rank: 오름차순에서 ceil(0.95 * N)번째 값.
    return len(times), median(times), times[ceil(0.95 * len(times)) - 1], times[-1], sum(s >= 500 for s, _ in samples)


def report(lines, min_count):
    groups = defaultdict(list)
    for line in lines:
        match = REQUEST.search(line)
        if match:
            route, status, ms = match.groups()
            groups[route].append((int(status), int(ms)))
    rows = []
    other = []
    for route, samples in sorted(groups.items()):
        if len(samples) < min_count:
            other.extend(samples)
        else:
            rows.append((route, *summarize(samples)))
    if other:
        rows.append(("그 밖", *summarize(other)))
    rows.append(("전체", *summarize([sample for samples in groups.values() for sample in samples])))
    return rows


def main():
    parser = argparse.ArgumentParser(description="서버 요청 시간 요약")
    parser.add_argument("--min-count", type=int, default=5)
    args = parser.parse_args()
    if args.min_count < 1:
        parser.error("--min-count 는 1 이상이어야 해요")
    print("주소 틀\t횟수\tp50 ms\tp95 ms\t최대 ms\t5xx 수")
    for row in report(sys.stdin, args.min_count):
        print(*row, sep="\t")


if __name__ == "__main__":
    main()
