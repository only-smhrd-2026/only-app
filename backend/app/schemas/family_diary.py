"""가족 일기 동무(AI 질문·초안) 요청·응답 모양 (FR-DI-006·007, D58).

화면 쪽 짝은 frontend/src/api/types.ts — 바꾸면 김승희를 리뷰어로. 부르는 화면은 FDIARY_002·003(박유승).
"""

from pydantic import BaseModel, Field, field_validator

from app.config import FAMILY_TEXT_MAX


class FamilyAskIn(BaseModel):
    text: str = Field(max_length=FAMILY_TEXT_MAX)  # 가족이 쓴 말 (앞뒤 빈칸을 뺀 뒤 1자 이상)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("일기 내용을 적어 주세요")
        return v


class FamilyAskOut(BaseModel):
    question: str  # 질문 1개. AI 가 실패하면 고정 질문


class FamilyDraftIn(FamilyAskIn):
    question: str = Field(default="", max_length=120)  # family-diary/ask 가 준 질문 그대로 (없으면 빈칸)
    answer: str = Field(default="", max_length=FAMILY_TEXT_MAX)  # 그 질문에 대한 답 (건너뛰면 빈칸 → 쓴 말만으로)

    @field_validator("question", "answer")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class FamilyDraftOut(BaseModel):
    body: str  # 가족 존댓말 1인칭 3~5문장. 가족이 고쳐 쓴 뒤 POST /rooms/{id}/diaries 로 올린다
