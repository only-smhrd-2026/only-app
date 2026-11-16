"""분류 채점의 분모·중복·실패·교집합·설명 비출력을 확인한다."""

import json
import sys

import pytest

from scripts import score_classify


def test_three_answers_scores_errors_and_unmatched_files():
    answers = [
        {"file": "a.jpg", "is_old": "Y", "season": "WINTER", "activity": "운동", "category": "즐기던 운동"},
        {"file": "b.jpg", "is_old": "N", "season": "SUMMER", "activity": "none", "category": "none"},
        {"file": "c.jpg", "is_old": "N", "season": "NONE", "activity": "카페", "category": "옛날 간식"},
        {"file": "only-answer.jpg"},
    ]
    results = [
        {
            "file": "a.jpg",
            "is_old": True,
            "season": "WINTER",
            "activity": "운동",
            "category": "none",
            "confidence": 0.5,
        },
        {
            "file": "b.jpg",
            "is_old": False,
            "season": "WINTER",
            "activity": "none",
            "category": "none",
            "confidence": 0.49,
        },
        {"file": "c.jpg", "error": "비밀 오류 본문"},
        {"file": "only-result.jpg", "error": "실패"},
    ]
    result = score_classify.score(answers, results)
    assert (result["matched"], result["answers_only"], result["results_only"], result["errors"]) == (3, 1, 1, 1)
    assert {key: metric["correct"] for key, metric in result["fields"].items()} == {
        "is_old": 2,
        "season": 1,
        "activity": 2,
        "category": 1,
    }
    assert all(metric["total"] == 3 for metric in result["fields"].values())
    assert result["activity_none"] == {"ai": 1, "answers": 1}
    assert result["high_confidence_activity"] == {"correct": 1, "total": 1, "accuracy": 1}
    assert len(result["mismatches"]) == 6
    assert "비밀 오류 본문" not in json.dumps(result, ensure_ascii=False)


def test_last_result_wins_and_is_old_requires_boolean():
    answers = [{"file": "a", "is_old": "Y", "season": "NONE", "activity": "none", "category": "none"}]
    result = {"file": "a", "is_old": 1, "season": "NONE", "activity": "none", "category": "none", "confidence": 0.9}
    scored = score_classify.score(answers, [{"file": "a", "error": "이전 실패"}, result])
    assert scored["errors"] == 0
    assert scored["fields"]["is_old"]["correct"] == 0
    assert scored["fields"]["activity"]["correct"] == 1
    scored = score_classify.score(answers, [result, {"file": "a", "error": "마지막 실패"}])
    assert scored["errors"] == 1 and scored["fields"]["activity"]["correct"] == 0


def test_empty_intersection_has_no_division_by_zero():
    result = score_classify.score([], [{"file": "only-result", "error": "fail"}])
    assert result["matched"] == 0 and result["results_only"] == 1
    assert result["high_confidence_activity"]["accuracy"] == 0
    assert all(metric["accuracy"] == 0 for metric in result["fields"].values())


@pytest.mark.parametrize("results", [{"file": "a"}, [None], [{"error": "missing file"}]])
def test_invalid_result_shape_is_rejected(results):
    with pytest.raises(ValueError):
        score_classify.score([], results)


def test_cli_omits_scene_and_raw_error(tmp_path, monkeypatch, capsys):
    answers = tmp_path / "answers.csv"
    answers.write_text(
        "file,owner,is_old,season,activity,category,memo\ntest_1.jpg,test,N,NONE,none,none,\n", encoding="utf-8"
    )
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            [
                {
                    "file": "test_1.jpg",
                    "is_old": False,
                    "season": "NONE",
                    "activity": "none",
                    "category": "none",
                    "confidence": 1,
                    "scene": "비밀 사진 설명",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["score_classify", "--answers", str(answers), "--results", str(results)])
    score_classify.main()
    output = capsys.readouterr().out
    assert "100.0%" in output and "비밀 사진 설명" not in output and "scene" not in output
