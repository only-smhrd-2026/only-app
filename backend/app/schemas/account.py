from pydantic import BaseModel, Field


class OwnerTransferIn(BaseModel):
    """내가 방장인 가족방 하나를 어떻게 할지 — 화면이 보여 준 그대로 보낸다. 서버가 본 것과 다르면 400."""

    room_id: int
    # 방장을 넘길 가족. null = 다른 가족이 없는 방이라 가족방과 어르신 기록을 전부 지우는 데 동의함 (칸을 빼면 안 됨)
    new_owner_user_id: int | None


class WithdrawIn(BaseModel):
    password: str = Field(max_length=64)  # 지금 비밀번호 (LoginIn 과 같은 길이)
    transfers: list[OwnerTransferIn] = Field(default_factory=list, max_length=100)  # 내가 방장인 가족방마다 1칸
