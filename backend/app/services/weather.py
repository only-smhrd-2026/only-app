"""어르신 동네 날씨 (D106) — 심심이 잡담이 '오늘 날씨 어때?'에 바로 답하게.

Open-Meteo(키 없음, 무료) 예보·대기질 API. 동네(시·도) 좌표만 보낸다 — 어르신·가족 정보는 보내지 않는다.
동네마다 WEATHER_CACHE_SEC 동안 같은 값을 쓰고, 실패하면 None → 심심이가 '지금은 날씨를 못 알아 왔어요'.
미세먼지 등급은 환경부 기준(PM10 30·80·150, PM2.5 15·35·75).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import (
    REGIONS,
    WEATHER_CACHE_SEC,
    WEATHER_COLD_FEELS,
    WEATHER_HOT_FEELS,
    WEATHER_TIMEOUT_SEC,
    WEATHER_WIND_MS,
)

log = logging.getLogger("app.weather")

FORECAST = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
# WMO 날씨 코드 → 쉬운 말 (코드 이하면 그 말). 4~44 같은 빈 번호는 오지 않는다
SKY = [(0, "맑음"), (2, "구름 조금"), (3, "흐림"), (48, "안개"), (57, "이슬비"), (67, "비"), (77, "눈"),
       (82, "소나기"), (86, "눈 소나기"), (99, "천둥 번개")]  # fmt: skip
# 하늘 말 → 심심이 날씨 그림 (11/26, 승희 님 그림). 여기 없는 하늘(맑음·흐림·안개)은 기온·바람으로 고른다
LOOK = {"눈": "snow", "눈 소나기": "snow", "소나기": "raincoat", "천둥 번개": "raincoat", "이슬비": "umbrella",
        "비": "umbrella"}  # fmt: skip
# ponytail: 동네별 캐시는 프로세스 메모리 (워커 1개 전제, D9). 재시작하면 처음 한 번 다시 받는다
_cache: dict[str, tuple[float, dict[str, str | None] | None]] = {}


def sky(code: int) -> str:
    return next((word for top, word in SKY if code <= top), "흐림")


def dust(value: float, cuts: tuple[int, int, int]) -> str:
    return ["좋음", "보통", "나쁨", "매우 나쁨"][sum(value > c for c in cuts)]


def look(code: int, feels: float, wind: float) -> str | None:
    """지금 날씨에 맞는 심심이 그림 이름 — 하늘 먼저, 다음 몸으로 느끼는 기온, 바람. 맑은 보통 날은 None(인사 그림)."""
    if sky(code) in LOOK:
        return LOOK[sky(code)]
    if feels <= WEATHER_COLD_FEELS:
        return "winter"
    if feels >= WEATHER_HOT_FEELS:
        return "hot"
    return "wind" if wind >= WEATHER_WIND_MS else None


def _day(d: dict[str, Any], i: int) -> str:
    rain = d["precipitation_probability_max"][i] or 0
    low, high = round(d["temperature_2m_min"][i]), round(d["temperature_2m_max"][i])
    return f"{sky(d['weather_code'][i])}, 최저 {low}도 최고 {high}도, 비 올 확률 {rain}%"


def _fetch(region: str) -> dict[str, str | None]:
    lat, lon = REGIONS[region]
    base = {"latitude": lat, "longitude": lon, "timezone": "Asia/Seoul"}
    with httpx.Client(timeout=WEATHER_TIMEOUT_SEC) as client:
        f = client.get(
            FORECAST,
            params=base
            | {
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "wind_speed_unit": "ms",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 2,
            },
        )
        f.raise_for_status()
        a = client.get(AIR, params=base | {"current": "pm10,pm2_5"})
        a.raise_for_status()
    now, daily, air = f.json()["current"], f.json()["daily"], a.json()["current"]
    return {
        "where": region,
        "now": f"{sky(now['weather_code'])}, {round(now['temperature_2m'])}도 "
        f"(몸으로 느끼기에는 {round(now['apparent_temperature'])}도)",
        "today": _day(daily, 0),
        "tomorrow": _day(daily, 1),
        "dust": f"미세먼지 {dust(air['pm10'], (30, 80, 150))}, 초미세먼지 {dust(air['pm2_5'], (15, 35, 75))}",
        "look": look(now["weather_code"], now["apparent_temperature"], now["wind_speed_10m"]),
    }


def for_region(region: str | None) -> dict[str, str] | None:
    """잡담 AI 에 넘길 동네 날씨 {where, now, today, tomorrow, dust}. 동네를 안 정했거나 받아 오지 못하면 None."""
    w = _get(region)
    return {k: v for k, v in w.items() if k != "look" and v is not None} if w else None


def look_for(region: str | None) -> str | None:
    """어르신 화면 심심이 날씨 그림 (11/26). 동네를 안 정했거나 받아 오지 못했거나 맑은 보통 날이면 None."""
    w = _get(region)
    return w.get("look") if w else None


def _get(region: str | None) -> dict[str, str | None] | None:
    if region not in REGIONS:
        return None
    hit = _cache.get(region)
    if hit and time.monotonic() - hit[0] < WEATHER_CACHE_SEC:
        return hit[1]
    try:
        value: dict[str, str | None] | None = _fetch(region)
    except Exception as e:  # 날씨가 안 와도 대화는 이어 간다 — 1분 뒤 다시 받아 본다
        log.warning("weather failed region=%s type=%s", region, type(e).__name__)
        _cache[region] = (time.monotonic() - WEATHER_CACHE_SEC + 60, None)
        return None
    _cache[region] = (time.monotonic(), value)
    return value
