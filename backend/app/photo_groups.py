"""사진첩 분류 칩 묶음 (11/23) — AI 분류 이름표(data/taxonomy.json, D76)를 칩 6개로 묶는 표. 서버는 여기 한 곳만 본다.

칩: FAMILY 가족 · TRAVEL 여행 · FOOD 음식 · NATURE 풍경 · EVENT 행사 · ETC 기타.
고르는 차례: 활동(가족이 고친 활동이 있으면 그것 먼저) → 활동이 없거나 none 이면 주제 → 둘 다 없으면 ETC(분류 전도 ETC).
taxonomy.json 에 이름표를 더하면 여기에도 더한다 — tests/test_data_files.py 가 빠진 값을 잡는다.
"""

from sqlalchemy import ColumnElement, and_, func, not_, or_

from app.models import Photo

GROUPS = ("FAMILY", "TRAVEL", "FOOD", "NATURE", "EVENT", "ETC")

ACTIVITY_GROUP = {
    "가족 식사": "FAMILY",
    "손주 돌보기": "FAMILY",
    "반려동물": "FAMILY",
    "겨울 놀이": "FAMILY",
    "여행": "TRAVEL",
    "소풍": "TRAVEL",
    "캠핑": "TRAVEL",
    "바닷가": "TRAVEL",
    "등산": "TRAVEL",
    "물놀이": "TRAVEL",
    "장날": "TRAVEL",
    "김장": "FOOD",
    "장 담그기": "FOOD",
    "떡 만들기": "FOOD",
    "요리": "FOOD",
    "카페": "FOOD",
    "꽃구경": "NATURE",
    "모내기": "NATURE",
    "농사": "NATURE",
    "잔치": "EVENT",
    "결혼식": "EVENT",
    "명절 차례": "EVENT",
    "생일": "EVENT",
    "운동회": "EVENT",
    "졸업식": "EVENT",
    "기념일": "EVENT",
    "학교 생활": "EVENT",
    "공연 구경": "EVENT",
    "운동": "ETC",
}
CATEGORY_GROUP = {
    "아이들 놀이": "FAMILY",
    "키우던 동물": "FAMILY",
    "다녀온 곳": "TRAVEL",
    "옛날 탈것": "TRAVEL",
    "여름 놀이": "TRAVEL",
    "잔칫상 음식": "FOOD",
    "김치 재료": "FOOD",
    "명절 음식": "FOOD",
    "떡 종류": "FOOD",
    "봄나물": "FOOD",
    "여름 과일": "FOOD",
    "겨울 음식": "FOOD",
    "해산물": "FOOD",
    "옛날 간식": "FOOD",
    "집밥 반찬": "FOOD",
    "소풍 도시락": "FOOD",
    "봄꽃": "NATURE",
    "농기구": "NATURE",
    "명절 놀이": "EVENT",
    "운동회 종목": "EVENT",
    "옛날 구경거리": "EVENT",
    "즐겨 부르던 노래": "EVENT",
    "장터 물건": "ETC",
    "부엌 살림": "ETC",
    "학교 물건": "ETC",
    "즐기던 운동": "ETC",
}


def group_of(photo: Photo) -> str:
    """사진 한 장의 칩. 아래 group_filter 와 같은 규칙이어야 한다."""
    activity = photo.corrected_activity or photo.activity
    if activity in ACTIVITY_GROUP:
        return ACTIVITY_GROUP[activity]
    return CATEGORY_GROUP.get(photo.category, "ETC")


def group_filter(group: str) -> ColumnElement[bool]:
    """?group= 으로 거르는 SQL 조건 — 쪽 나누기(before)·장수 상한이 DB 에서 맞게. NULL 은 'none' 으로 본다."""
    activity = func.coalesce(Photo.corrected_activity, Photo.activity, "none")
    category = func.coalesce(Photo.category, "none")

    def match(g: str) -> ColumnElement[bool]:
        acts = [a for a, v in ACTIVITY_GROUP.items() if v == g]
        cats = [c for c, v in CATEGORY_GROUP.items() if v == g]
        return or_(activity.in_(acts), and_(activity.not_in(list(ACTIVITY_GROUP)), category.in_(cats)))

    if group == "ETC":
        return not_(or_(*(match(g) for g in GROUPS if g != "ETC")))
    return match(group)
