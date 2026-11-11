"""사진 정답표 검사·합치기 (backend 폴더에서 실행):
cd backend && uv run python -m scripts.check_answers a.csv b.csv --out all.csv"""

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
        end = 0  # 앞 행이 끝난 줄
        try:
            with path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source, strict=True)
                if reader.fieldnames != FIELDS:
                    received = ",".join(reader.fieldnames or [])
                    errors.append(
                        f"{path.name} 1째 줄: 첫 줄 제목이 달라요. "
                        f"받은 제목: {received!r}, 올바른 제목: {','.join(FIELDS)}"
                    )
                    continue
                end = reader.line_num
                for row in reader:
                    # memo 가 여러 줄이면 line_num 은 끝 줄이라, 시트 행 번호와 맞게 시작 줄을 쓴다
                    # ponytail: 아주 빈 줄(DictReader 가 건너뜀) 뒤 행은 그만큼 앞 줄로 나온다
                    line, end = end + 1, reader.line_num
                    normalized = {key: row.get(key) or "" for key in FIELDS}
                    if not any(normalized.values()) and not any(row.get(None, ())):
                        continue  # 구글 시트가 끝에 붙이는 빈 행(,,,,,,)
                    location = f"{path.name} {line}째 줄"
                    if None in row:
                        errors.append(f"{location}: 제목보다 칸이 많아요")
                    rows.append(normalized)
                    for key in FIELDS[:-1]:
                        value = normalized[key]
                        if not value.strip():
                            errors.append(f"{location}: {key} 칸이 비어 있어요")
                        elif key in ("file", "owner") and value != value.strip():
                            errors.append(f"{location}: {key} 앞뒤에 띄어쓰기가 있어요: {value!r}")
                    for key, values in {"is_old": {"Y", "N"}, "season": SEASONS, **allowed}.items():
                        value = normalized[key]
                        if value.strip() and value not in values:
                            errors.append(f"{location}: {key} 값이 올바르지 않아요: {value!r}")
                    filename, owner = normalized["file"].strip(), normalized["owner"].strip()
                    if filename and owner and not filename.startswith(f"{owner}_"):
                        errors.append(f"{location}: file 이름이 '{owner}_'로 시작하지 않아요: {filename!r}")
                    if filename:
                        if filename in seen:
                            errors.append(
                                f"{location}: 같은 file이 두 번 있어요: {filename!r} (처음: {seen[filename]})"
                            )
                        else:
                            seen[filename] = location
        except FileNotFoundError:
            errors.append(f"{path.name}: 파일을 찾을 수 없어요 ({path})")
        except UnicodeError:
            errors.append(
                f"{path.name}: UTF-8 글자가 아니라 읽을 수 없어요. "
                "엑셀은 'CSV UTF-8'로 저장하고, 구글 시트는 파일 > 다운로드 > CSV로 내려받아 주세요"
            )
        except csv.Error as exc:
            errors.append(f'{path.name} {end + 1}째 줄: 따옴표(")가 깨졌어요. 이 줄의 따옴표를 확인해 주세요 ({exc})')
        except OSError as exc:
            errors.append(f"{path.name}: 파일을 읽을 수 없어요 ({type(exc).__name__})")
    return rows, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="사진 정답표 CSV를 검사하고 합칩니다.")
    parser.add_argument("paths", nargs="+", type=Path, help="검사할 CSV 파일")
    parser.add_argument("--out", type=Path, help="오류가 없을 때 저장할 합친 CSV")
    args = parser.parse_args()
    if args.out:
        # samefile: 맥의 한글 이름(NFC/NFD)·대소문자가 달라도 같은 파일을 잡는다
        if args.out.exists() and any(path.exists() and args.out.samefile(path) for path in args.paths):
            sys.exit(f"--out 이 검사할 파일과 같아요. 다른 이름으로 저장해 주세요: {args.out}")
        if not args.out.parent.is_dir():
            sys.exit(f"--out 폴더가 없어요: {args.out.parent}")
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
