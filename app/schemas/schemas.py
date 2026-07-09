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
    dpr1: str  # 당일가
    dpr5: str  # 전월가
    dpr7: str  # 평년가
    unit: str


class JudgePriceOutput(BaseModel):
    status: Literal["비쌈", "적정", "쌈"]
    diff_pct: float


class SubstituteOutput(BaseModel):
    substitutes: List[str]
    source: str
