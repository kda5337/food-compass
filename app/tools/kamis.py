from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.schemas import RawPriceOutput
from app.tools.price_cache import get_price_cache, save_price_cache

if TYPE_CHECKING:
    from app.graph.state import AgentState

_MOCK_DATA_PATH = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "kamis_mock.json"
)


def _load_mock() -> dict[str, dict]:
    with open(_MOCK_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_raw_price_mock(item_name: str) -> RawPriceOutput | None:
    """tests/fixtures/kamis_mock.json에서 해당 품목 반환 — Day3에 실 KAMIS API 호출로 교체."""
    data = _load_mock()
    if item_name not in data:
        return None
    return RawPriceOutput(**data[item_name])


def get_raw_price_node(state: AgentState) -> dict[str, Any]:
    """Day3: 실제 KAMIS API 연동 전까지 mock 조회 + Supabase 캐시 저장/Fallback으로 대체.

    - mock 조회 성공 → price_cache에 저장 (§11-1 흐름의 "조회 성공 시 캐시 갱신" 최소 구현)
    - mock에 없는 품목 → price_cache 조회로 Fallback 시도
    """
    items = state.get("items", [])
    price_data = []
    for item_name in items:
        result = get_raw_price_mock(item_name)
        if result is not None:
            price_data.append(result.model_dump())
            try:
                save_price_cache(item_name, result)
            except Exception as e:
                print(f"[get_raw_price] 캐시 저장 실패: {e}")
        else:
            cached = None
            try:
                cached = get_price_cache(item_name)
            except Exception as e:
                print(f"[get_raw_price] 캐시 조회 실패: {e}")

            if cached is not None:
                price_data.append(cached)
            else:
                # 미등록 품목: 결측치로 채워 후속 노드가 처리
                price_data.append(
                    {"item_name": item_name, "dpr1": "-", "dpr5": "-", "dpr7": "-", "unit": "-"}
                )
    return {"price_data": price_data}
