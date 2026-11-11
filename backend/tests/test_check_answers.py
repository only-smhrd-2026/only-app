"""정답표 값 검증과 CLI의 오류 종료·합친 파일 저장을 확인한다."""

import csv
import json
import subprocess
import sys

import pytest

from app.config import ROOT
from scripts.check_answers import FIELDS, check


def _row(filename="test_01.jpg", **changes):
    taxonomy = json.loads((ROOT / "data" / "taxonomy.json").read_text(encoding="utf-8"))
    return {
        "file": filename,
        "owner": "test_owner",
        "is_old": "Y",
        "season": "SPRING",
        "activity": taxonomy["activity"][0],
        "category": taxonomy["category"][0],
        "memo": "",
    } | changes


def _write(path, rows, fields=FIELDS):
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_merge_four_rows(tmp_path):
    first = [_row(), _row("test_02.jpg", memo="쉼표, 메모\n다음 줄")]
    second = [_row("test_03.jpg", activity="none", category="none"), _row("test_04.jpg", is_old="N")]
    paths = [_write(tmp_path / "a.csv", first), _write(tmp_path / "b.csv", second)]
    rows, errors = check(paths)
    assert rows == first + second
    assert errors == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"activity": "목록에 없는 활동"}, "activity"),
        ({"category": "목록에 없는 주제"}, "category"),
        ({"season": "FALL"}, "season"),
        ({"is_old": "예"}, "is_old"),
        ({"activity": " none"}, "activity"),
        ({"category": "none "}, "category"),
        ({"owner": "  "}, "owner 칸이 비어"),
        ({"file": ""}, "file 칸이 비어"),
    ],
)
def test_invalid_value(tmp_path, changes, message):
    path = _write(tmp_path / "invalid.csv", [_row(**changes)])
    _, errors = check([path])
    assert len(errors) == 1
    assert "invalid.csv 2째 줄:" in errors[0] and message in errors[0]


def test_duplicate_across_files(tmp_path):
    paths = [_write(tmp_path / name, [_row()]) for name in ("a.csv", "b.csv")]
    rows, errors = check(paths)
    assert len(rows) == 2
    assert len(errors) == 1 and "b.csv 2째 줄: 같은 file이 두 번" in errors[0]


def test_wrong_header_skips_file(tmp_path):
    bad = _write(tmp_path / "bad.csv", [_row(season="FALL")], list(reversed(FIELDS)))
    good = _write(tmp_path / "good.csv", [_row()])
    rows, errors = check([bad, good])
    assert len(rows) == 1 and len(errors) == 1
    assert "bad.csv 1째 줄: 첫 줄 제목이 달라요" in errors[0]
    assert ",".join(FIELDS) in errors[0]


def test_cli_only_writes_valid_merge(tmp_path):
    first = _write(tmp_path / "a.csv", [_row()])
    second = _write(tmp_path / "b.csv", [_row("test_02.jpg", season="FALL")])
    output = tmp_path / "all.csv"
    command = [sys.executable, "-m", "scripts.check_answers", str(first), str(second), "--out", str(output)]
    invalid = subprocess.run(command, cwd=ROOT / "backend", capture_output=True)
    assert invalid.returncode == 1 and not output.exists()
    _write(second, [_row("test_02.jpg")])
    valid = subprocess.run(command, cwd=ROOT / "backend", capture_output=True)
    assert valid.returncode == 0, valid.stderr
    rows, errors = check([output])
    assert len(rows) == 2 and not errors
