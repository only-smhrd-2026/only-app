"""정답표 값 검증과 CLI의 오류 종료·합친 파일 저장을 확인한다."""

import csv
import json
import os
import subprocess
import sys

import pytest

from app.config import ROOT
from scripts.check_answers import FIELDS, check


def _row(filename="test_01.jpg", **changes):
    taxonomy = json.loads((ROOT / "data" / "taxonomy.json").read_text(encoding="utf-8"))
    return {
        "file": filename,
        "owner": "test",
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
        ({"file": "other_01.jpg"}, "'test_'로 시작하지 않아요"),
        ({"file": "test01.jpg"}, "'test_'로 시작하지 않아요"),
        ({"file": "test_01.jpg "}, "file 앞뒤에 띄어쓰기"),
        ({"owner": " test"}, "owner 앞뒤에 띄어쓰기"),
    ],
)
def test_invalid_value(tmp_path, changes, message):
    path = _write(tmp_path / "invalid.csv", [_row(**changes)])
    _, errors = check([path])
    assert len(errors) == 1
    assert "invalid.csv 2째 줄:" in errors[0] and message in errors[0]


@pytest.mark.parametrize(("second", "count"), [("test_01.jpg", 1), (" test_01.jpg", 2)])
def test_duplicate_across_files(tmp_path, second, count):
    """앞뒤 띄어쓰기가 붙은 같은 이름도 띄어쓰기 오류와 함께 겹침으로 잡는다."""
    paths = [_write(tmp_path / "a.csv", [_row()]), _write(tmp_path / "b.csv", [_row(second)])]
    rows, errors = check(paths)
    assert len(rows) == 2 and len(errors) == count
    assert "b.csv 2째 줄: 같은 file이 두 번" in errors[-1]


@pytest.mark.parametrize("blank", [",,,,,,", ",,,,,,,", ","])
def test_blank_rows_skipped(tmp_path, blank):
    """구글 시트가 끝에 붙이는 빈 행은 행 수에도 오류에도 넣지 않는다."""
    path = _write(tmp_path / "a.csv", [_row()])
    with path.open("a", encoding="utf-8", newline="") as target:
        target.write(f"{blank}\r\n" * 3)
    rows, errors = check([path])
    assert rows == [_row()] and errors == []


def test_line_is_record_start(tmp_path):
    """memo 가 여러 줄이어도 시트 행과 같은 시작 줄 번호를 알려 준다."""
    path = _write(
        tmp_path / "a.csv", [_row(season="FALL", memo="첫째\n둘째\n셋째"), _row("test_02.jpg", season="FALL")]
    )
    _, errors = check([path])
    assert [error.split(":")[0] for error in errors] == ["a.csv 2째 줄", "a.csv 5째 줄"]


@pytest.mark.parametrize(
    ("tail", "encoding", "message"),
    [
        (None, None, "bad.csv: 파일을 찾을 수 없어요"),
        ("", "cp949", "'CSV UTF-8'로 저장"),
        ('test_02.jpg,"te"st,Y,SPRING,none,none,\r\n', "utf-8", "bad.csv 3째 줄: 따옴표"),
        ('"test_02.jpg,test,Y,SPRING,none,none,\r\n', "utf-8", "bad.csv 3째 줄: 따옴표"),
    ],
)
def test_read_failure_hint(tmp_path, tail, encoding, message):
    """읽기 실패는 영어 예외 이름 대신 고칠 방법을 한글로 알려 준다."""
    path = tmp_path / "bad.csv"
    if tail is not None:
        text = _write(tmp_path / "good.csv", [_row()]).read_text(encoding="utf-8-sig")
        path.write_bytes((text + tail).encode(encoding))
    _, errors = check([path])
    assert len(errors) == 1 and message in errors[0]


def test_wrong_header_skips_file(tmp_path):
    bad = _write(tmp_path / "bad.csv", [_row(season="FALL")], list(reversed(FIELDS)))
    good = _write(tmp_path / "good.csv", [_row()])
    rows, errors = check([bad, good])
    assert len(rows) == 1 and len(errors) == 1
    assert "bad.csv 1째 줄: 첫 줄 제목이 달라요" in errors[0]
    assert ",".join(FIELDS) in errors[0] and ",".join(reversed(FIELDS)) in errors[0]


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


@pytest.mark.parametrize(("out", "message"), [("a.csv", "검사할 파일과 같아요"), ("missing/all.csv", "폴더가 없어요")])
def test_cli_refuses_bad_out(tmp_path, out, message):
    """--out 이 입력 파일이거나 없는 폴더면 덮어쓰지 않고 한글로 알려 준다."""
    source = _write(tmp_path / "a.csv", [_row()])
    before = source.read_bytes()
    command = [sys.executable, "-m", "scripts.check_answers", str(source), "--out", str(tmp_path / out)]
    # 한국어 Windows 는 자식 출력이 cp949 — 받는 쪽과 같게 utf-8 로 고정한다
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(command, cwd=ROOT / "backend", capture_output=True, encoding="utf-8", env=env)
    assert result.returncode == 1 and message in result.stderr and "Traceback" not in result.stderr
    assert source.read_bytes() == before
