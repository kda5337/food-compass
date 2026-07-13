from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.schemas.schemas import JudgePriceOutput

if TYPE_CHECKING:
    from app.graph.state import AgentState

_EXPENSIVE_THRESHOLD = 5.0   # 평년 대비 +10% 초과 → 비쌈
_CHEAP_THRESHOLD = -5.0      # 평년 대비 -10% 미만 → 쌈

# 무게 단위 → 그램 환산 계수
_WEIGHT_UNIT_TO_GRAM = {"kg": 1000, "g": 1}

# 개수 기반 단위 (1개당으로 환산할 대상)
_COUNT_UNITS = {"개", "속", "단", "포기", "마리", "봉", "팩", "모"}


def parse_price(price_str: str) -> float | None:
    """콤마 포함 문자열("3,606") 또는 결측치("-")를 float으로 변환."""
    if not price_str or price_str.strip() == "-":
        return None
    try:
        return float(price_str.replace(",", "").strip())
    except ValueError:
        return None


def _pct_diff(current: float | None, past: float | None) -> float | None:
    if current is None or past is None or past == 0:
        return None
    return round((current - past) / past * 100, 1)

def normalize_price_unit(
    price: float | None, unit: str | None
) -> tuple[float | None, str | None]:
    """가격을 표준 단위로 환산.

    - 무게 단위(kg, g)는 100g당 가격으로 변환.
    - 개수 단위(개, 속, 단 등)는 1개당 가격으로 변환.
    - unit이 없거나("" / None), 형식을 인식할 수 없으면 변환하지 않고 원본 그대로 반환.

    예시:
        normalize_price_unit(3000, "1kg")   -> (300.0, "100g")
        normalize_price_unit(3000, "20kg")  -> (15.0, "100g")
        normalize_price_unit(500, "100g")   -> (500.0, "100g")  # 이미 100g 기준
        normalize_price_unit(5000, "10개")  -> (500.0, "1개")
        normalize_price_unit(3000, "1개")   -> (3000.0, "1개")
        normalize_price_unit(3000, "")      -> (3000, "")        # 스킵
        normalize_price_unit(3000, "1속")   -> (3000.0, "1속")
    """
    if price is None or not unit:
        return price, unit

    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z가-힣]+)\s*$", unit.strip())
    if not match:
        # "1kg" 같은 숫자+단위 형식이 아니면 인식 불가 — 변환 스킵
        return price, unit

    qty = float(match.group(1))
    unit_label = match.group(2)

    if unit_label in _WEIGHT_UNIT_TO_GRAM:
        total_grams = qty * _WEIGHT_UNIT_TO_GRAM[unit_label]
        if total_grams <= 0:
            return price, unit
        normalized_price = round(price / total_grams * 100, 1)
        return normalized_price, "100g"

    if unit_label in _COUNT_UNITS:
        if qty <= 0:
            return price, unit
        normalized_price = round(price / qty, 1)
        return normalized_price, f"1{unit_label}"

    # 알려지지 않은 단위(예: "1단(500g)" 같은 복합 표기)는 변환하지 않고 그대로 반환
    return price, unit

def judge_price(
    dpr1: str, dpr7: str, dpr3: str | None = None, dpr5: str | None = None, unit: str | None = None,
) -> JudgePriceOutput:
    """당일가(dpr1)를 평년가(dpr7)와 비교하여 비쌈/적정/쌈 판정.

    dpr3(1주일전)·dpr5(1개월전)이 주어지면 참고용 등락률도 함께 계산 — 판정 기준(비쌈/적정/쌈)은
    평년가 대비로 유지하되, 답변 생성 시 최근 추세를 함께 설명할 수 있도록 부가 정보로 제공.
    """
    last_week = parse_price(dpr3)
    last_month = parse_price(dpr5)
    avg = parse_price(dpr7)
    normalized_price, normalized_unit = normalize_price_unit(last_week, unit)
    print( f"[normalize_price_unit] 원본: {last_week} {unit} "
    f"-> 변환: {normalized_price} {normalized_unit}")

    if last_week is None or last_month is None or avg == 0:
        return JudgePriceOutput(status="적정", diff_pct=0.0)

    diff_pct = (last_week - last_month) / avg * 100

    if diff_pct > _EXPENSIVE_THRESHOLD:
        status = "비쌈"
    elif diff_pct < _CHEAP_THRESHOLD:
        status = "쌈"
    else:
        status = "적정"

    week_diff_pct = _pct_diff(last_week, last_month) if dpr3 is not None else None
    month_diff_pct = _pct_diff(last_month, avg) if dpr5 is not None else None

    return JudgePriceOutput(
        status=status,
        diff_pct=round(diff_pct, 1),
        week_diff_pct=week_diff_pct,
        month_diff_pct=month_diff_pct,
        normalized_price = normalized_price,
        unit=normalized_unit,
    )


def judge_price_node(state: AgentState) -> dict[str, Any]:
    price_data = state.get("price_data", [])
    judgments = []
    for item in price_data:
        if not item.get("found", True):
            # DB 미등록 품목 — 임의 추정 금지, "미지원"으로 표시해 답변 생성 단계에서 안내
            judgments.append(
                {
                    "item_name": item.get("item_name"),
                    "status": "미지원",
                    "diff_pct": None,
                    "week_diff_pct": None,
                    "month_diff_pct": None,
                }
            )
            continue

        result = judge_price(
            item.get("dpr1", "-"),
            item.get("dpr7", "-"),
            item.get("dpr3", "-"),
            item.get("dpr5", "-"),
            item.get("unit"),
        )
        judgments.append(
            {
                "item_name": item.get("item_name"),
                "status": result.status,
                "diff_pct": result.diff_pct,
                "week_diff_pct": result.week_diff_pct,
                "month_diff_pct": result.month_diff_pct,
                # 답변 생성 단계에서 실제 금액을 지어내지 않도록 조회된 값 그대로 전달
                "today_price": result.normalized_price,
                "unit": result.unit,
                # [2026-07-14 추가] today_price가 fallback(며칠 전 값)인 경우 답변에서
                # "N일 전 기준"으로 밝히기 위해 전달 — "당일"이면 별도 표기 안 함
                "price_as_of": item.get("price_as_of"),
            }
        )
    return {"judgment": judgments}
