"""사진 분류 결과를 정답표와 비교한다. AI 호출·사진 설명 출력은 하지 않는다."""

import argparse
import json
import math
from pathlib import Path

from scripts.check_answers import check

FIELDS = ("is_old", "season", "activity", "category")


def score(answers: list[dict], results: list[dict]) -> dict:
    """같은 파일의 마지막 결과를 사용한다. 분류 실패는 공통 파일의 오답으로 세고 원문 오류는 출력하지 않는다."""
    if not isinstance(answers, list) or not isinstance(results, list):
        raise ValueError("정답과 결과는 줄 목록이어야 해요")
    truth, predictions = {}, {}
    for rows, target in ((answers, truth), (results, predictions)):
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("file"), str) or not row["file"].strip():
                raise ValueError("모든 줄에는 file 이름이 있어야 해요")
            target[row["file"]] = row
    shared = sorted(truth.keys() & predictions.keys())
    metrics = {field: {"correct": 0, "total": len(shared)} for field in FIELDS}
    mismatches = []
    errors = ai_none = answer_none = high_correct = high_total = 0
    for filename in shared:
        answer, result = truth[filename], predictions[filename]
        failed = "error" in result
        errors += failed
        answer_none += answer.get("activity") == "none"
        ai_none += not failed and result.get("activity") == "none"
        for field in FIELDS:
            expected = answer.get(field)
            if field == "is_old":
                if expected not in ("Y", "N"):
                    raise ValueError("정답 is_old 값은 Y 또는 N이어야 해요")
                expected = expected == "Y"
            actual = None if failed else result.get(field)
            if actual is not None and not isinstance(actual, (str, bool, int, float)):
                raise ValueError("분류 값은 단일 값이어야 해요")
            correct = not failed and actual == expected and (field != "is_old" or type(actual) is bool)
            metrics[field]["correct"] += correct
            if not correct:
                mismatches.append({"file": filename, "field": field, "actual": actual, "expected": expected})
        confidence = result.get("confidence")
        if not failed and type(confidence) in (int, float) and math.isfinite(confidence) and confidence >= 0.5:
            high_total += 1
            high_correct += result.get("activity") == answer.get("activity")
    for metric in metrics.values():
        metric["accuracy"] = metric["correct"] / metric["total"] if metric["total"] else 0
    return {
        "matched": len(shared),
        "answers_only": len(truth.keys() - predictions.keys()),
        "results_only": len(predictions.keys() - truth.keys()),
        "errors": errors,
        "fields": metrics,
        "activity_none": {"ai": ai_none, "answers": answer_none},
        "high_confidence_activity": {
            "correct": high_correct,
            "total": high_total,
            "accuracy": high_correct / high_total if high_total else 0,
        },
        "mismatches": mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="사진 분류 결과를 정답표와 비교합니다. AI는 호출하지 않습니다.")
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    answers, errors = check([args.answers])
    if errors:
        for error in errors:
            print(error)
        parser.exit(1, "정답표 오류를 먼저 고쳐 주세요\n")
    try:
        results = json.loads(args.results.read_text(encoding="utf-8-sig"))
        summary = score(answers, results)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.exit(1, f"분류 결과를 읽을 수 없어요 ({type(exc).__name__})\n")
    print("field               | correct / total | accuracy")
    for field, metric in summary["fields"].items():
        print(f"{field:19} | {metric['correct']} / {metric['total']} | {metric['accuracy']:.1%}")
    high = summary["high_confidence_activity"]
    print(f"activity(conf>=0.5) | {high['correct']} / {high['total']} | {high['accuracy']:.1%}")
    print(f"activity none: AI {summary['activity_none']['ai']}, 정답 {summary['activity_none']['answers']}")
    print(
        f"정답만 있음 {summary['answers_only']}, 결과만 있음 {summary['results_only']}, 분류 실패 {summary['errors']}"
    )
    print("file | field | AI | answer")
    for row in summary["mismatches"]:
        print(f"{row['file']} | {row['field']} | {row['actual']} | {row['expected']}")


if __name__ == "__main__":
    main()
