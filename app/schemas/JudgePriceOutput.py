from typing import Literal

from pydantic import BaseModel, Field


class RawPriceOutput(BaseModel):
    """KAMIS 원시 가격 조회 출력 스키마.

    KAMIS 실제 응답 필드명 기준:
    - item_name: 품목명
    - dpr1: 당일가
    - dpr5: 전월가
    - dpr7: 평년가
    - unit: 단위
    """
    item_name: str = Field(..., description="품목명")
    dpr1: str | None = Field(None, description="당일가")
    dpr5: str | None = Field(None, description="전월가")
    dpr7: str | None = Field(None, description="평년가")
    unit: str | None = Field(None, description="가격 단위")

class JudgePrice(BaseModel):
    """가격 판단 결과.
    status:
      - 비쌈: 당일가가 평년가보다 유의미하게 높음
      - 적정: 평년가 대비 큰 차이 없음
      - 쌈: 당일가가 평년가보다 유의미하게 낮음
    diff_pct: (dpr1 - dpr7) / dpr7 * 100
      양수면 평년가보다 비싼 방향, 음수면 싼 방향
    """
    status: Literal["비쌈", "적정", "쌈"] = Field(
        ..., description="평년가 대비 당일가 판단 결과")
    diff_pct: float = Field(
        ..., description="평년가 대비 당일가 차이 비율(%)")