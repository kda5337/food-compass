from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from app.core.state import AgentState
from app.schemas.JudgePriceOutput import RawPriceOutput

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
    items = state.get("items", [])
    price_data = []
    for item_name in items:
        result = get_raw_price_mock(item_name)
        if result is not None:
            price_data.append(result.model_dump())
        else:
            # 미등록 품목: 결측치로 채워 후속 노드가 처리
            price_data.append(
                {"item_name": item_name, "dpr1": "-", "dpr5": "-", "dpr7": "-", "unit": "-"}
            )
    return {"price_data": price_data}
