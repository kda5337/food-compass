from __future__ import annotations
from typing import TYPE_CHECKING, Any

from app.tools.judge import parse_price
from app.tools.price_snapshot import get_latest_prices

if TYPE_CHECKING:
    from app.graph.state import AgentState

_DPR_FIELDS = ("dpr1", "dpr2", "dpr3", "dpr4", "dpr5", "dpr6", "dpr7")
_PREFERRED_RANK = "상품"  # 여러 등급(상품/중품 등) 중 대표로 삼을 등급


def _pick_representative_row(rows: list[dict]) -> dict:
    """같은 품목의 여러 품종·등급 row 중 대표 1건 선택 — '상품' 등급 우선, 없으면 첫 row."""
    for row in rows:
        if row.get("rank_name") == _PREFERRED_RANK:
            return row
    return rows[0]


def _resolve_today_price(row: dict) -> dict:
    """당일가(dpr1)가 '-'(당일 데이터 미반영)이면 전일가(dpr2)로 대체."""
    resolved = dict(row)
    if parse_price(resolved.get("dpr1", "-")) is None:
        fallback = resolved.get("dpr2", "-")
        if parse_price(fallback) is not None:
            resolved["dpr1"] = fallback
    return resolved


def get_raw_price_node(state: AgentState) -> dict[str, Any]:
    """Supabase price_snapshot에서 실제 KAMIS 시세(당일·1주일전·1개월전·평년)를 조회.

    - DB에 없는 품목은 found=False로 표시 — 값을 임의로 채우지 않음(§11-3, 미지원 품목 안내).
    - DB 조회 자체가 실패하면(연결 오류 등) 동일하게 미지원으로 처리.
    """
    items = state.get("items", [])
    price_data = []
    for item_name in items:
        try:
            rows = get_latest_prices(item_name)
        except Exception as e:
            print(f"[get_raw_price] DB 조회 실패: {e}")
            rows = []

        if not rows:
            price_data.append(
                {
                    "item_name": item_name,
                    "unit": "-",
                    "found": False,
                    **{field: "-" for field in _DPR_FIELDS},
                }
            )
            continue

        row = _resolve_today_price(_pick_representative_row(rows))
        price_data.append(
            {
                "item_name": row["item_name"],
                "unit": row["unit"],
                "found": True,
                **{field: row.get(field, "-") for field in _DPR_FIELDS},
            }
        )
    return {"price_data": price_data}
