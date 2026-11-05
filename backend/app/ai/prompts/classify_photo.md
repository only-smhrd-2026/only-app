# 사진 분류 (FR-ME-003) — 자리표시

담당자가 채운다 (김영중 몫이었으나 11/9 재배정). 입력: 사진 1장 + data/taxonomy.json 의 activity·category 목록(JSON 데이터).
출력(JSON): usable(bool), is_old(bool), season(SPRING|SUMMER|AUTUMN|WINTER|NONE), activity(목록 중 하나 또는 "none"),
category(목록 중 하나 또는 "none"), confidence(0~1). photo_meta 테이블 컬럼과 같다.
목록 밖 값은 코드에서 "none" 으로 바꾼다 (인젝션 피해를 오분류로 한정, D14).
