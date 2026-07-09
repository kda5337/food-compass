from __future__ import annotations
from typing import Any

from app.graph.state import AgentState
from app.schemas import JudgePriceOutput

_EXPENSIVE_THRESHOLD = 10.0   # 평년 대비 +10% 초과 → 비쌈
_CHEAP_THRESHOLD = -10.0      # 평년 대비 -10% 미만 → 쌈


def parse_price(price_str: str) -> float | None:
    """콤마 포함 문자열("3,606") 또는 결측치("-")를 float으로 변환."""
    if not price_str or price_str.strip() == "-":
        return None
    try:
        return float(price_str.replace(",", "").strip())
    except ValueError:
        return None


def judge_price(dpr1: str, dpr7: str) -> JudgePriceOutput:
    """당일가(dpr1)를 평년가(dpr7)와 비교하여 비쌈/적정/쌈 판정."""
    today = parse_price(dpr1)
    avg = parse_price(dpr7)

    if today is None or avg is None or avg == 0:
        return JudgePriceOutput(status="적정", diff_pct=0.0)

    diff_pct = (today - avg) / avg * 100

    if diff_pct > _EXPENSIVE_THRESHOLD:
        status = "비쌈"
    elif diff_pct < _CHEAP_THRESHOLD:
        status = "쌈"
    else:
        status = "적정"

    return JudgePriceOutput(status=status, diff_pct=round(diff_pct, 1))


def judge_price_node(state: AgentState) -> dict[str, Any]:
    price_data = state.get("price_data", [])
    judgments = []
    for item in price_data:
        result = judge_price(item.get("dpr1", "-"), item.get("dpr7", "-"))
        judgments.append(
            {
                "item_name": item.get("item_name"),
                "status": result.status,
                "diff_pct": result.diff_pct,
            }
        )
    return {"judgment": judgments}
