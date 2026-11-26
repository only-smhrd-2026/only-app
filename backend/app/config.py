"""설정 1곳. .env(저장소 루트)를 읽고, 값이 없으면 개발용 기본값으로 mock 실행이 되게 한다.

시간대는 여기서만 정한다(설계 결정 D12): TZ, now_kst(), today_kst() 외에 datetime.now()를 직접 쓰지 않는다.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

DAILY_ALERT_HOUR = 19  # 하루 기록 알림 예약 시각 (KST)

ROOT = Path(__file__).resolve().parents[2]  # only-app/
TZ = ZoneInfo("Asia/Seoul")

# 개발 기본값. 배포(APP_ENV=deploy)에서 이 값 그대로면 기동 거부 (D20 + "값 없이 실행" 절충)
DEV_JWT_SECRET = "dev-only-jwt-secret-change-me-before-deploy-0000"

# 상한값은 설정 테이블 대신 상수 (D8)
# 회상 AI 질문 수(어제 이야기 질문 포함): 사진 3 → 문제 1 → 사진 1 (D97, 11/24 전 4·11/18 전 6·11/12 전 8). DB CHECK 0~8
MAX_TURNS = 5
# 일기 대화 질문 수: 뭐 하셨어요 → 아직 안 나온 것 3번(누구랑·어디서·그다음 …) → 기분은 (FR-DI-003, D97 — 11/24 전 3)
DIARY_TURNS = 5
DIARY_DRAFT_MIN = 30  # 일기 초안 유지 시간 (FR-DI-004)
QUIZ_TURN = MAX_TURNS - 1  # 끝에서 두 번째 AI 질문이 생각 문제 — 어제 이야기 질문도 세는 순번 (FR-AI-002, D42·D79)
QUIZ_PER_DAY = 2  # 가족방 하루 문제 상한 (FR-AI-002 '하루 1~2문제'). 세션당은 1개
QUIZ_REPEAT_DAYS = 14  # 최근 14일에 쓴 활동·주제·문제는 빼고 고른다 (D39)
QUIZ_ROTATE_DAYS = 90  # 같은 칸 안에서는 이 기간에 안 낸 문제 → 가장 오래전에 낸 문제 순으로 고른다 (D72)
# 사진 분류 신뢰도가 이 미만이면 none 사진으로 본다 (FR-ME-003). 11/14 테스트 사진 15장: 맞은 활동 14장이 모두 0.6 이상,
# 그중 9장이 0.6 이라 0.7 → 0.5 (D71). 월요일 정답표(#20)로 다시 본다
PHOTO_CONF_MIN = 0.5
MAX_SESSION_SEC = 300  # 5분 (대화한 시간)
# 마지막 답에 '더 얘기할래'가 있으면 끊지 않고 질문·시간을 한 번 더 준다 (11/25 실사용 — 회상·사진첩·일기 모두)
MORE_TURNS = 3
MORE_SESSION_SEC = 180
# 끝난 회상·사진첩 대화의 [더 이야기할래요] — 그 대화를 다시 열어 질문 MORE_TURNS 개·시간 MORE_SESSION_SEC 를 더 준다.
# 한 대화에 이만큼까지 (D110, 11/26 사용자 '2번까지')
MORE_ROUNDS = 2
PAUSE_GAP_SEC = 90  # 턴 사이가 이보다 길면 보류로 보고 90초만 센다 (무응답 3단계 60초 + 여유)
ALBUM_PER_DAY = 3
ALBUM_TURNS = 2  # 사진첩 대화 장당 AI 질문 수 (FR-ME-008)
# 심심이 잡담 (D106, 11/25 멘토 아이디어): 홈의 심심이를 누르면 아무 이야기나·궁금한 것 무엇이든. DB CHECK 0~30
CHAT_TURNS = 20  # 한 번 잡담의 심심이 말 수 — 넘으면 '또 불러 주세요' 마무리 (돈은 이 수와 아래 하루 몫으로 막는다)
CHAT_SESSION_SEC = 20 * 60  # 잡담은 대화한 시간 20분까지 (회상·일기 5분 MAX_SESSION_SEC 와 따로)
CHAT_CONTEXT_TURNS = 16  # 잡담 AI 에 넘기는 최근 말 수 (그 앞은 넘기지 않는다 — 토큰)
CHAT_LIST_LIMIT = 50  # '지난 이야기' 목록 수, 최신 순
CHAT_LIST_DAYS = 30  # '지난 이야기' 목록은 최근 30일
# 어르신 동네(가족방 weather_region) → 날씨 좌표. 시·도청 근처 (D106). 날씨는 Open-Meteo(키 없음) — services/weather.py
REGIONS: dict[str, tuple[float, float]] = {
    "서울": (37.5665, 126.9780),
    "부산": (35.1796, 129.0756),
    "대구": (35.8714, 128.6014),
    "인천": (37.4563, 126.7052),
    "광주": (35.1595, 126.8526),
    "대전": (36.3504, 127.3845),
    "울산": (35.5384, 129.3114),
    "세종": (36.4801, 127.2890),
    "경기": (37.2752, 127.0095),
    "강원": (37.8854, 127.7298),
    "충북": (36.6358, 127.4914),
    "충남": (36.6588, 126.6728),
    "전북": (35.8203, 127.1088),
    "전남": (34.8161, 126.4629),
    "경북": (36.5760, 128.5056),
    "경남": (35.2383, 128.6925),
    "제주": (33.4996, 126.5312),
}
# 도 안의 시·군 (D111, 11/26 사용자 '영광·해남이 전남 하나로 묶인다') — 가족방에는 '전남 영광군'처럼 남는다.
# 좌표: Open-Meteo 지오코딩(소속 시·군이 그 이름인 곳, 시·군청 마을 먼저), 거기 없는 25곳은 OpenStreetMap.
# 광역시·세종은 하나
_TOWNS_FILE = ROOT / "data" / "regions.json"
TOWNS: dict[str, dict[str, tuple[float, float]]] = {
    do: {name: (lat, lon) for name, (lat, lon) in towns.items()}
    for do, towns in json.loads(_TOWNS_FILE.read_text("utf-8")).items()
}
# 날씨를 받을 수 있는 이름 전부 — 시·도(11/25 부터 고른 방은 그대로) + '시·도 시·군'
PLACES: dict[str, tuple[float, float]] = REGIONS | {
    f"{do} {n}": p for do, towns in TOWNS.items() for n, p in towns.items()
}
WEATHER_CACHE_SEC = 30 * 60  # 동네마다 30분 동안 같은 날씨를 쓴다
WEATHER_TIMEOUT_SEC = 3.0  # 날씨 서버를 기다리는 시간 — 넘으면 날씨 없이(모른다고) 대화를 이어 간다
# 날씨 심심이 그림 기준 (11/26 사용자: 하늘 먼저, 다음 기온·바람) — 몸으로 느끼는 기온(도)·바람(초속 m)
WEATHER_RAIN_PROB = 60  # 지금 맑아도 오늘 비·눈 올 확률(%)이 이 이상이면 우산·눈 심심이 (D109)
WEATHER_COLD_FEELS = 10  # 이하면 목도리 심심이 (D109 — 5 → 10, 어르신은 추위에 약해 늦가을부터)
WEATHER_HOT_FEELS = 28  # 이상이면 더운 심심이
WEATHER_WIND_MS = 7  # 이상이면 바람 심심이 (D109 — 9 → 7)
# 어르신 사진첩 '내 일기' 목록이 한 번에 돌려주는 개수(최신 순) — 사진 목록 PHOTO_LIST_LIMIT 와 같은 값 (D8)
ELDER_DIARY_LIST_LIMIT = 100
# 가족 소식 첫 장 '하트가 왔어요'가 한 번에 받는 가족 이모지·한마디 수. 넘으면 들은 뒤 나머지가 나온다 (D63)
ELDER_HEARTS_LIMIT = 20
REPLY_MAX = 40  # 가족이 어르신 일기에 남기는 한마디 글자 수 (11/19) — 화면 HOME_002 의 REPLY_MAX 와 같은 값
# 가족 목소리 답장 (D99, 11/24 사용자): 길이 상한(화면 HOME_002 VOICE_MS 와 같게),
# 저장 mp3 고정 비트레이트(길이 = 바이트 / (KBPS × 125)), 받아 적은 자막 글자 수
VOICE_REPLY_MAX_SEC = 30
ELDER_VOICE_REPLY_MAX_SEC = 60  # 어르신 [말로 답하기] 녹음 상한(화면 REPLY_MS)과 같게 — 저장하는 소리 길이 (11/25)
VOICE_REPLY_KBPS = 48
VOICE_REPLY_MAX_CHARS = 200
DIARY_MONTH_LIMIT = 300  # 달력(가족 일기 달력·어르신 지난 가족 소식)이 한 달·하루에 읽는 일기 수 상한 (11/25)
# 가족 사진 목록·어르신 사진첩이 한 번에 돌려주는 장수(최신 순) — 두 화면이 같은 사진을 보이게 한 값으로 (D8)
PHOTO_LIST_LIMIT = 100
NOTI_LIST_LIMIT = 50  # 가족 알림 목록이 한 번에 돌려주는 개수, 최신 순
ELDER_PUSH_PER_DAY = 2
SESSION_RESUME_MIN = 30  # 마지막 턴 후 30분 지나면 ENDED 취급
STT_CONF_MIN = 0.7  # 이 미만이면 확인 질문
STT_FAIL_LOCK = 2  # 세션 안 저신뢰 2회 → input_locked
NO_RESPONSE_END = 3  # 무응답 3단계째 종료
SESSION_ERROR_ALERT = 3  # 하루 ERROR 종료 3회 → 가족 알림
PICK_SKIP_ALERT = 2  # 같은 사진 건너뛰기 2회 → 가족 알림 (FR-ME-005)
NO_RECORD_DAYS = 2  # 이 날수만큼 어르신 기록이 없으면 가족 알림 (FR-NT-003)
WEEKLY_HOUR = 19  # 주간 집계는 일요일 이 시각, D19 — 집계 창과 예약 시각이 같이 쓴다
WEEKLY_CARDS_MAX = 4  # 주간 이야기의 질문·답 카드 수 (D62)
WEEKLY_PAIRS_MAX = 60  # 주간 요약 AI 에 주는 질문·답 쌍 수. 넘으면 긴 답부터 고른다
WEEKLY_STT_MIN = 0.7  # 음성 인식 신뢰도가 이보다 낮은 답은 가족에게 전하지 않는다 (FR-FD-006)
INTEGRATION_TREND_WEEKS = 4  # 꼬마심심이 연동 요약의 대화량 추이가 담는 주 수 — 그 주까지 최근 4주 (FR-API-002)
# 주간 이야기 '이번 주 달라진 점' (11/18 멘토링) — services/weekly.changes 가 그 주를 앞 주들과 견줄 때 쓴다
WEEKLY_BASE_WEEKS = 4  # 바로 앞 이만큼의 주를 '평소'로 본다
WEEKLY_BASE_MIN_WEEKS = 2  # 앞 주가 이보다 적으면 견주지 않는다 (처음 몇 주는 평소를 모른다)
WEEKLY_DAYS_GAP = 2  # 이야기한 날이 평소보다 이만큼 이상 다르면 '줄었다·늘었다'
WEEKLY_TALK_SHORT = 0.7  # 한마디 길이가 평소의 이 비율보다 짧으면 '짧아졌어요'
WEEKLY_TALK_LONG = 1.3  # 한마디 길이가 평소의 이 비율보다 길면 '길어졌어요'
WEEKLY_MOOD_LOW_DAYS = 2  # 속상했어요·쓸쓸했어요를 고르신 날이 한 주에 이만큼이면 살펴볼 것으로 알린다
WEEKLY_RUDE_MIN = 2  # 거친 말·성적인 말이 한 주에 이만큼이면 주간 요약에 횟수만 한 줄 (D112 — 한 번은 넘어간다)
STORY_HOUR = 4  # 새벽 이 시각에 어제 대화에서 이야기 기억을 뽑는다 — 가족방마다 AI 1번 (FR-AI-007, D77)
STORY_FACTS_MAX = 3  # 하루치 대화에서 뽑는 기억 수 상한
STORY_LOOKBACK_DAYS = 7  # 이어 물을 기억을 찾는 날수 — 이 안에서 가장 최근 대화한 날의 기억 하나 (FR-AI-008, D77)
STORY_KEEP_DAYS = 30  # 기억 보관 날수 — 지나면 새벽 작업이 지운다 (DBR-013 [가정])
MOOD_LOW_DAYS = 2  # 기운 없는 말이 나온 날이 최근 MOOD_LOW_WINDOW_DAYS 일 중 이만큼이면 가족 알림 1건 (D55 ②)
MOOD_LOW_WINDOW_DAYS = 7  # 위 날수를 세는 기간이자, 같은 알림을 다시 보내지 않는 기간
# 일기 사진이 옛 사진이면(분류 is_old + 신뢰도 이 이상) 일기 1·2번 질문을 그 사진 속 그때로 (FR-DI-002, D58)
OLD_PHOTO_CONF_MIN = 0.8
FAMILY_TEXT_MAX = 200  # 가족 일기 한마디·답 글자 수 (FR-DI-006)
FAMILY_DRAFT_MAX = 200  # 가족 일기 AI 초안 글자 수 — 어르신 가족 소식 화면에 한 번에 보이는 만큼 (D61)
FAMILY_AI_RATE_PER_MIN = 10  # 가족 일기 동무(질문·초안) 같은 사람 분당 상한. 한 사람이 하루 상한을 다 쓰지 못하게 (D58)
STT_MAX_BYTES = 5 * 1024 * 1024
STT_MAX_SEC = 60  # 녹음 상한 (FR-VS-001, 화면 RECORD_MS). 더 긴 소리는 변환할 때 잘라 STT 과금·메모리를 막는다
# 전사 상한. 턴 본문 상한(schemas/sessions.py TurnIn.text)과 같게 — 넘으면 턴이 422 로 대화를 끝낸다
STT_MAX_CHARS = 500
UPLOAD_MAX_BYTES = 10 * 1024 * 1024
UPLOAD_MAX_FILES = 20  # 한 번에 올리는 사진 수 (D17)
# 사진 한마디(caption)·사진 속 사람(people_note) 글자 수 — photos 표의 VARCHAR(100) 과 같게 (D17)
UPLOAD_MAX_NOTE_CHARS = 100
UPLOAD_MAX_PIXELS = 30_000_000  # 사진 한 장 픽셀 수(가로×세로). 넘으면 거절 — 서버 메모리 보호 (D17)
UPLOAD_MAX_SIDE = 65_500  # 사진 한 변 픽셀. 길쭉한 조작 그림(1×3천만)은 줄 주소표만 240MB — JPEG 한계와 같게 (D17)
UPLOAD_MAX_EXIF_BYTES = 64 * 1024  # 사진 정보(EXIF). 폰 사진은 64KB 안 — 넘으면 회전·촬영일을 읽지 않음 (D17)
UPLOAD_MAX_ICC_BYTES = 64 * 1024  # 색 프로필(ICC). 넘거나 RGB 프로필이 아니면 프로필 없이 저장 (D17)
UPLOAD_MAX_EXIF_SEGMENTS = 4  # 파일 속 EXIF 조각 수. 보통 1개, 여러 장 묶음도 2~3개 — 넘으면 거절 (D17)
JPEG_MAX_SCANS = 300  # JPEG 스캔(FF DA) 수. 보통 1~10개, 움직이는 사진 뒤 영상에서 우연히 나오는 것까지 넉넉히 (D17)
PHOTO_MAX_SIDE = 2560  # 저장 사진 긴 변(px). 넘으면 비율 그대로 줄여 저장 (D17)
UPLOAD_LOCK_WAIT_SEC = 60  # 사진 변환은 서버 전체에서 한 번에 한 요청. 이만큼 기다려도 차례가 안 오면 503 (D17)
LOGIN_RATE_PER_MIN = 10
LOGIN_FAIL_PER_EMAIL = 10
LOGIN_FAIL_WINDOW_SEC = 900
STT_RATE_PER_MIN = 20  # 같은 IP 의 /api/stt 분당 상한. 대화 한 번(5분)에 많아야 16번 부른다 (D46)
# 어르신 화면이 읽는 글(팝업·안내·가족 소식·지난 일기)을 고른 목소리로 (D78). 화면이 60자 안팎 묶음으로 나눠 보낸다
SPEECH_MAX_CHARS = 200  # 한 번에 받는 글자 수 — 200자 합성 약 5초(tts.py 실측). 넘으면 422 → 화면이 기기 목소리로
SPEECH_RATE_PER_MIN = 30  # 같은 가족방 분당 상한 — 넘으면 소리 없이(null) 돌려줘 화면이 기기 목소리로 읽는다
# 서버 전체 하루 상한 — 돈이 드는 호출(rtzr·google·anthropic)만 세고 한국 자정에 0 (D46 ⑨). 가입은 누구나 된다.
# 회상 대화 1번 ≈ Claude 6·TTS 6·STT 5(되묻기까지 최대 10)번, 일기 대화 1번 ≈ Claude 5·TTS 6·STT 4~5번 (D97).
# 300 이면 하루 회상+일기 한 쌍 약 25번(TTS 12번이 먼저 찬다, D97 전 약 33번) — 11/27 검증판 배포 때 다시 정함
STT_PER_DAY = 300  # 리턴제로. 넘으면 429 → 화면이 그 문장을 읽고 버튼으로
TTS_PER_DAY = 300  # Google. 넘으면 브라우저 목소리 (D5, 가족 알림 없음)
LLM_PER_DAY = 300  # Claude call_json 1번(검증 재시도 포함 최대 2요청). 넘으면 고정 문장 (D14)
# 가족 쪽 몫 (11/19) — 가입은 누구나 되므로, 가족 쿠키로 부르는 호출이 위 300 을 다 써도 어르신 대화 몫(나머지)은 남긴다
STT_FAMILY_PER_DAY = 150  # 가족 쿠키만 있는 /api/stt. 넘으면 그 요청만 429
LLM_FAMILY_PER_DAY = 150  # 가족 일기 동무(질문·초안). 넘으면 고정 질문·쓴 말 그대로의 초안 (D58 의 실패 때와 같은 길)
# 심심이 잡담(D106)은 위 300 과 따로 센다 — 잡담을 많이 해도 회상·일기 몫은 남는다. 넘으면 고정 문장
LLM_CHAT_PER_DAY = 300
# 사진 분류(Claude 비전, AI-04)는 위 300 과 따로 센다 — 사진을 많이 올려도 어르신 대화 몫을 안 쓴다 (D71)
CLASSIFY_PER_DAY = 200  # 넘으면 남은 가족 사진은 다음 날 이어서, 어르신 카메라 사진은 평소 일기
CLASSIFY_BATCH = 20  # 예약 작업 한 번에 분류하는 가족 사진 수 (가족이 한 번에 올리는 최대 장수와 같게)
CLASSIFY_EVERY_MIN = 10  # 가족 사진 분류 간격(분). 오늘의 한 장은 오늘 올린 사진을 안 고르므로 늦어도 된다
CLASSIFY_SYNC_SEC = 4.0  # 어르신 카메라 사진을 일기 대화 열 때 분류하는 시간 상한 — 넘으면 평소 일기 (실측 뒤 조정)
CLASSIFY_IMAGE_SIDE = 1024  # 분류에 보내는 사진 긴 변(px). 저장본(2560)보다 작게 — 토큰·보내는 시간을 줄인다
SESSION_COOKIE_DAYS = 7
DEVICE_COOKIE_DAYS = 365
KAKAO_STEP_MIN = 10  # 카카오 로그인 중간 쿠키(state·가입 대기) 수명(분) — 카카오 화면에서 머무는 시간
KAKAO_TIMEOUT_SEC = 5.0  # 카카오 서버(토큰·회원번호) 응답을 기다리는 시간. 넘으면 로그인 화면으로 돌려보낸다
MOOD_WEEK_DAYS = 7  # 가족 홈 마음 카드가 보여 주는 날수
MOOD_CHECK_EVERY_DAYS = 14  # 마음 체크 초대 간격 — 마지막 마음 체크 뒤 이 날수가 지나면 다시 권함, D56
MOOD_CHECK_DOWN_MIN = 5  # PHQ-8·PHQ-9 답 합이 이 이상이면 DOWN '조금 가라앉으신 편이에요' (공식 '가벼움' 5점부터)
MOOD_CHECK_HARD_MIN = (
    10  # PHQ-8·PHQ-9 답 합이 이 이상이면 HARD '많이 힘드신 것 같아요' (공식 '중간' 10점부터). DOWN 미만은 USUAL
)
MOOD_HISTORY_LIMIT = 10  # 어르신 '내 마음' 지난 결과 수, 최신 순 (11/23)
# 힘든 말씀(마음 위급) 뒤 위로 대화 (D94 바꿈, 11/23): 대화를 끝내지 않고 이만큼 더 위로한 뒤 마무리한다.
# 위로 턴은 질문 수(MAX_TURNS)·5분 상한과 따로 센다 — 위로 도중에 시간이 다 됐다고 끊지 않게. 돈은 이 수로 막는다
COMFORT_TURNS = 3
# 웹 푸시 (app/services/push.py)
PUSH_TIMEOUT_SEC = 5  # 푸시 서비스(FCM·애플·모질라)를 한 번 부를 때 기다리는 시간
PUSH_TTL_SEC = 24 * 3600  # 폰이 꺼져 있으면 푸시 서비스가 이만큼 맡아 뒀다 전한다. 어르신 시간 알림은 그날 자정까지만
PUSH_JWT_SEC = 12 * 3600  # VAPID 서명(JWT) 유효 시간 — RFC 8292 상한은 24시간
PUSH_SUBS_PER_USER = 5  # 가족 한 사람이 알림을 받는 브라우저 수. 넘으면 오래전에 등록한 것부터 지운다
# 추억 알림은 추억 시간 뒤 이 시간 안에만 보낸다 — 서버가 아침에 꺼져 있었다고 밤에 어르신 폰을 울리지 않게 (FR-NT-002)
MEMORY_REMINDER_HOURS = 2
URGENT_REMIND_MIN = 30  # 위급 알림에 [제가 연락했어요]가 이 분 동안 없으면 가족에게 한 번 더 알린다 (11/19 응급)
URGENT_SHOW_HOURS = 24  # 가족 홈 긴급 카드가 보이는 시간 — 확인한 뒤에도 '○○님이 연락했어요'로 이만큼 남는다
URGENT_CHECK_EVERY_MIN = 5  # 위 '한 번 더 알림'을 살피는 예약 작업 간격
WITHDRAW_REAUTH_MIN = 10  # 비밀번호가 없는 카카오 회원은 로그인한 지 이 분 안에만 탈퇴할 수 있다 (11/19 보안 점검)
CARE_BASE_DAYS = 14  # 돌봄 루프가 '평소'로 보는 날수 — 오늘 전 이만큼의 기록과 견준다 (11/19)
CARE_BASE_MIN_DAYS = 5  # 말수 비교는 이야기한 날이 이만큼 쌓인 뒤부터 (처음 며칠은 평소를 모른다)
CARE_TALK_DOWN = 0.6  # 어제 한마디 길이가 평소 평균의 이 비율보다 짧으면 '말수가 줄었어요'
CARE_ASK_GAP_DAYS = 2  # 같은 안부는 이 날수에 한 번 — 어제 여쭌 안부는 오늘 쉰다
CARE_ASK_MAX = 3  # 같은 안부는 평소 기간 안에 이만큼까지만 여쭌다
CARE_KEEP_DAYS = 90  # 돌봄 일지 보관 날수 — 지나면 지운다
PICK_LEARN_DAYS = 60  # 오늘의 한 장을 고를 때 돌아보는 날수 — 슬퍼하신 사진을 쉬게 하는 기간이기도 하다 (11/19)
PICK_LIKE = 1.2  # 한 주제의 대화가 전체 평균의 이 배수보다 길면 '좋아하시는 주제'로 본다


class Settings(BaseSettings):
    # env_ignore_empty: .env 에 "KEY=" 처럼 비워 둔 값은 기본값으로 (값 없이 mock 실행)
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_ignore_empty=True)

    APP_ENV: str = "dev"  # dev | deploy
    DATABASE_URL: str = "postgresql+psycopg://only:only@127.0.0.1:5432/only_app"
    JWT_SECRET: str = DEV_JWT_SECRET
    SCHEDULER_ENABLED: bool = True

    ANTHROPIC_API_KEY: str = ""
    # 비우면 Anthropic 직접. MonoRouter: https://monogpt.kr/api/monorouter/v1/anthropic (11/24, 키 mr_anthropic_…)
    ANTHROPIC_BASE_URL: str = ""
    LLM_PROVIDER: str = "mock"  # mock | anthropic
    LLM_MODEL: str = "claude-haiku-5-5"
    STT_PROVIDER: str = "mock"  # mock | rtzr | ...
    TTS_PROVIDER: str = "mock"  # mock | google | ...
    IMAGE_PROVIDER: str = "mock"  # mock | cloudflare

    STORAGE: str = "local"  # local | r2
    UPLOAD_DIR: str = str(ROOT / "uploads")
    DOMAIN: str = ""

    # 카카오 로그인 (FR-AD-001 2순위). REST 키나 돌아올 주소가 비면 카카오 로그인 전체가 꺼진다(routers/kakao.py)
    KAKAO_REST_KEY: str = ""
    KAKAO_CLIENT_SECRET: str = ""  # 카카오 콘솔에서 'Client Secret' 을 켰을 때만
    KAKAO_REDIRECT_URI: str = ""  # 예 https://<도메인>/api/auth/kakao/callback — 요청의 Host 를 믿지 않고 이 값만 쓴다

    # 이름만 예약 (키를 받으면 .env 에 채움)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = ""
    RTZR_CLIENT_ID: str = ""
    RTZR_CLIENT_SECRET: str = ""
    GOOGLE_TTS_API_KEY: str = ""
    CF_ACCOUNT_ID: str = ""
    CF_API_TOKEN: str = ""
    # 웹 푸시 VAPID 키 (만들기: uv run python -m scripts.vapid_keys). 두 키가 비어 있으면 푸시를 보내지 않는다
    VAPID_PUBLIC_KEY: str = ""  # base64url, 풀면 65바이트 — 화면이 구독할 때 받아 간다
    VAPID_PRIVATE_KEY: str = ""  # base64url, 풀면 32바이트
    VAPID_SUBJECT: str = ""  # mailto:운영자 주소 또는 https://주소 — 애플(아이폰) 푸시는 이 값이 없으면 거절한다

    # 꼬마심심이 연동 요약 API 의 Bearer 키. 비어 있으면(기본값) 그 주소가 꺼진다 (FR-API-003).
    # 기업과 계약을 확정하기 전에는 운영 서버에서도 비워 둔다
    INTEGRATION_API_KEY: str = ""

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV == "dev"


settings = Settings()

if len(settings.JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET 은 32자 이상이어야 합니다 (.env)")
if not settings.is_dev and settings.JWT_SECRET == DEV_JWT_SECRET:
    raise RuntimeError("배포 환경(APP_ENV=deploy)에서는 JWT_SECRET 을 개발 기본값으로 둘 수 없습니다")
# 연동 키는 인터넷에서 어르신 요약을 막는 하나뿐인 문 — 짧으면 여러 IP 로 맞혀 볼 수 있다(틀린 키 제한은 IP 별)
if 0 < len(settings.INTEGRATION_API_KEY) < 32:
    raise RuntimeError("INTEGRATION_API_KEY 는 32자 이상이어야 합니다 (.env). 비워 두면 연동이 꺼집니다")


def now_kst() -> datetime:
    return datetime.now(TZ)


def today_kst() -> date:
    return now_kst().date()
