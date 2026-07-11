from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    user_query: str
    route: str
    items: list[str]
    price_data: list[dict[str, Any]]
    judgment: list[dict[str, Any]]
    knowledge_result: str
    substitutes: list[str]
    answer: str
