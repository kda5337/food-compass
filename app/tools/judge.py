from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.schemas import JudgePriceOutput

if TYPE_CHECKING:
    from app.graph.state import AgentState

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


def _pct_diff(current: float | None, past: float | None) -> float | None:
    if current is None or past is None or past == 0:
        return None
    return round((current - past) / past * 100, 1)


def judge_price(
    dpr1: str, dpr7: str, dpr3: str | None = None, dpr5: str | None = None
) -> JudgePriceOutput:
    """당일가(dpr1)를 평년가(dpr7)와 비교하여 비쌈/적정/쌈 판정.

    dpr3(1주일전)·dpr5(1개월전)이 주어지면 참고용 등락률도 함께 계산 — 판정 기준(비쌈/적정/쌈)은
    평년가 대비로 유지하되, 답변 생성 시 최근 추세를 함께 설명할 수 있도록 부가 정보로 제공.
    """
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

    week_diff_pct = _pct_diff(today, parse_price(dpr3)) if dpr3 is not None else None
    month_diff_pct = _pct_diff(today, parse_price(dpr5)) if dpr5 is not None else None

    return JudgePriceOutput(
        status=status,
        diff_pct=round(diff_pct, 1),
        week_diff_pct=week_diff_pct,
        month_diff_pct=month_diff_pct,
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
        )
        judgments.append(
            {
                "item_name": item.get("item_name"),
                "status": result.status,
                "diff_pct": result.diff_pct,
                "week_diff_pct": result.week_diff_pct,
                "month_diff_pct": result.month_diff_pct,
                # 답변 생성 단계에서 실제 금액을 지어내지 않도록 조회된 값 그대로 전달
                "today_price": item.get("dpr1"),
                "unit": item.get("unit"),
                # [2026-07-14 추가] today_price가 fallback(며칠 전 값)인 경우 답변에서
                # "N일 전 기준"으로 밝히기 위해 전달 — "당일"이면 별도 표기 안 함
                "price_as_of": item.get("price_as_of"),
            }
        )
    return {"judgment": judgments}
