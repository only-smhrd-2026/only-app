"""카카오 로그인 요청·응답 (routers/kakao.py). 화면 쪽 짝은 frontend/src/api/types.ts."""

from typing import Literal

from pydantic import BaseModel, Field


class ProvidersOut(BaseModel):
    kakao: bool  # 서버에 카카오 키가 있을 때만 true. false 면 화면이 '준비 중'으로 보인다


class KakaoPendingOut(BaseModel):
    nickname: str  # 카카오 닉네임(없으면 빈 글자) — 가입 화면 이름 칸에 미리 넣는 용도


class KakaoSignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    terms_agreed: Literal[True]  # 약관 동의 없이는 가입 불가 (NFR-AN-004) — 이메일 가입(SignupIn)과 같다
