from __future__ import annotations
import re
from typing import Any, Set

from .state import AgentState
from app.prompts.prompts import ROUTER_SYSTEM_PROMPT  # noqa: F401 — Day3 LLM 연동 시 사용
from app.schemas import RouterOutput

# 가격 관련 키워드 (mock router 전용)
_PRICE_KEYWORDS: Set[str] = {
    "비싸", "비싼", "싸다", "저렴", "시세", "가격", "얼마", "원",
    "사도", "사야", "구매", "살만", "요즘", "지금", "할만", "비쌈", "쌈",
}

# 식품 품목 목록 (mock router 전용)
_FOOD_ITEMS: Set[str] = {
    "상추", "배추", "오이", "당근", "깻잎", "파", "마늘", "감자", "고추",
    "양파", "무", "시금치", "브로콜리", "양배추", "애호박", "가지", "토마토",
    "사과", "딸기", "바나나", "수박", "참외", "포도", "복숭아",
    "쌀", "고구마", "콩나물", "두부",
}

# 품목명 뒤에 붙어도 식품 언급으로 인정할 한국어 조사 목록
_PARTICLES = {
    "가", "이", "는", "은", "을", "를", "의", "도", "에", "로", "으로",
    "와", "과", "랑", "이랑", "에서", "이나", "나", "하고", "만",
    "까지", "부터", "마저", "조차", "이며", "며", "이고", "고",
}


def _item_in_query(item: str, query: str) -> bool:
    """품목명이 공백 분리 토큰 안에서 온전히 포함되는지 확인.

    - "오이랑" → "오이" + 조사 "랑" → 매칭
    - "파이썬" → "파" + "이썬"(조사 아님) → 미매칭
    """
    for token in re.split(r"[\s?!.,~]", query):
        if not token.startswith(item):
            continue
        remainder = token[len(item):]
        if remainder == "" or remainder in _PARTICLES:
            return True
    return False


def _mock_router(query: str) -> RouterOutput:
    """키워드 기반 Mock 라우터 — Day3에 실제 Upstage Solar LLM 호출로 교체."""
    found_items = [item for item in _FOOD_ITEMS if _item_in_query(item, query)]
    has_price_keyword = any(kw in query for kw in _PRICE_KEYWORDS)

    if found_items or has_price_keyword:
        return RouterOutput(route="price", items=found_items)
    return RouterOutput(route="off-topic", items=[])


def router_node(state: AgentState) -> dict[str, Any]:
    query = state["user_query"]
    result = _mock_router(query)
    return {"route": result.route, "items": result.items}
