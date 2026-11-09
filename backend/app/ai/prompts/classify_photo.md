# 사진 분류 (FR-ME-003) — 자리표시

홍진성이 채운다 (AI-04 #29, 2주차). 입력: 사진 1장 + data/taxonomy.json 의 activity·category 목록(JSON 데이터).
출력(JSON): usable(bool), is_old(bool), season(SPRING|SUMMER|AUTUMN|WINTER|NONE), activity(목록 중 하나 또는 "none"),
category(목록 중 하나 또는 "none"), confidence(0~1). photos 테이블의 분류 칸과 같다.
목록 밖 값은 코드에서 "none" 으로 바꾼다 (인젝션 피해를 오분류로 한정, D14).
고르는 기준은 data/taxonomy.json 의 `_rules` 한 곳에 있다(11/13 정답표 안내와 같은 문장) — 채울 때 이 파일에 옮겨 쓰지 말고 system 에 같이 넣는다. 근거가 없으면 none, 없는 단서를 지어내지 않는다.
