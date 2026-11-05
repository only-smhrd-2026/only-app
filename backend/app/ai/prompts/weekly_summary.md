# 주간 이야기 요약 (FR-FD-005/006) — 자리표시

홍진성이 11/23~ 채운다. 입력(JSON 데이터): 집계 창(지난 일요일 19:00 ~ 이번 일요일 19:00 KST)의 세션 턴·일기·되짚기 결과.
출력(JSON): weekly_summaries 테이블의 qa_list, recall_check, mood_trend, talk_volume(어절), diaries, notes.
규칙 검사(rule_check_passed)는 코드에서: 금지어 없음, 어르신이 말하지 않은 내용 없음(source_turn_id 대조), baseline_talk NULL 이면 추이·경고 생략.
