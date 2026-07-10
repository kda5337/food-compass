from __future__ import annotations
from typing import List, Literal
from pydantic import BaseModel


class RouterOutput(BaseModel):
    route: Literal["price", "off-topic"]
    items: List[str]


class RawPriceInput(BaseModel):
    item_name: str


class RawPriceOutput(BaseModel):
    item_name: str
    unit: str
    dpr1: str  # 당일가
    dpr2: str  # 1일전
    dpr3: str  # 1주일전
    dpr4: str  # 2주일전
    dpr5: str  # 1개월전
    dpr6: str  # 1년전
    dpr7: str  # 평년가


class JudgePriceOutput(BaseModel):
    status: Literal["비쌈", "적정", "쌈"]
    diff_pct: float  # 평년(dpr7) 대비
    week_diff_pct: float | None = None   # 1주일전(dpr3) 대비
    month_diff_pct: float | None = None  # 1개월전(dpr5) 대비


class SubstituteOutput(BaseModel):
    substitutes: List[str]
    source: str
