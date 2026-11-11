"""사진 정답표 검사·합치기: uv run python -m scripts.check_answers a.csv b.csv --out all.csv"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from app.config import ROOT

FIELDS = ["file", "owner", "is_old", "season", "activity", "category", "memo"]
SEASONS = {"SPRING", "SUMMER", "AUTUMN", "WINTER", "NONE"}


def check(paths: list[str | Path]) -> tuple[list[dict[str, str]], list[str]]:
    """입력 순서대로 모든 행과 파일명·줄 번호를 붙인 오류 문장을 돌려준다."""
    taxonomy = json.loads((ROOT / "data" / "taxonomy.json").read_text(encoding="utf-8"))
    allowed = {key: set(taxonomy[key]) | {"none"} for key in ("activity", "category")}
    rows, errors = [], []
    seen: dict[str, str] = {}
    for path in map(Path, paths):
        line = 1
        try:
            with path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source, strict=True)
                if reader.fieldnames != FIELDS:
                    errors.append(f"{path.name} 1째 줄: 첫 줄 제목이 달라요. 올바른 제목: {','.join(FIELDS)}")
                    continue
                for row in reader:
                    line = reader.line_num
                    location = f"{path.name} {line}째 줄"
                    if None in row:
                        errors.append(f"{location}: 제목보다 칸이 많아요")
                    normalized = {key: row.get(key) or "" for key in FIELDS}
                    rows.append(normalized)
                    for key in FIELDS[:-1]:
                        if not normalized[key].strip():
                            errors.append(f"{location}: {key} 칸이 비어 있어요")
                    for key, values in {"is_old": {"Y", "N"}, "season": SEASONS, **allowed}.items():
                        value = normalized[key]
                        if value.strip() and value not in values:
                            errors.append(f"{location}: {key} 값이 올바르지 않아요: {value!r}")
                    filename = normalized["file"]
                    if filename.strip():
                        if filename in seen:
                            errors.append(
                                f"{location}: 같은 file이 두 번 있어요: {filename!r} (처음: {seen[filename]})"
                            )
                        else:
                            seen[filename] = location
        except (OSError, UnicodeError, csv.Error) as exc:
            errors.append(f"{path.name} {line}째 줄: 파일을 읽을 수 없어요 ({type(exc).__name__})")
    return rows, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="사진 정답표 CSV를 검사하고 합칩니다.")
    parser.add_argument("paths", nargs="+", type=Path, help="검사할 CSV 파일")
    parser.add_argument("--out", type=Path, help="오류가 없을 때 저장할 합친 CSV")
    args = parser.parse_args()
    rows, errors = check(args.paths)
    for error in errors:
        print(error)
    print(f"전체 {len(rows)}줄, 틀린 곳 {len(errors)}개")
    if errors:
        sys.exit(1)
    if args.out:
        with args.out.open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
