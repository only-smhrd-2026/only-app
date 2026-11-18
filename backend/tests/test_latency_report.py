from scripts.latency_report import report


def test_report_groups_routes_and_calculates_latency():
    lines = [f"api | req method=GET route=/api/rooms/{{room_id}} status=200 ms={n}" for n in range(1, 21)]
    lines += [
        "req method=POST route=/api/login status=503 ms=50",
        "req method=GET route=- status=404 ms=1",
        "unrelated log",
    ]
    assert report(lines, 5) == [
        ("/api/rooms/{room_id}", 20, 10.5, 19, 20, 0),
        ("그 밖", 2, 25.5, 50, 50, 1),
        ("전체", 22, 10.5, 20, 50, 1),
    ]


def test_empty_report_has_zero_totals():
    assert report([], 5) == [("전체", 0, 0, 0, 0, 0)]
