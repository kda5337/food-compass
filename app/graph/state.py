from __future__ import annotations
from typing import Any, Dict, List, TypedDict


class AgentState(TypedDict, total=False):
    user_query: str
    route: str
    items: List[str]
    price_data: List[Dict[str, Any]]
    judgment: List[Dict[str, Any]]
    knowledge_result: str
    substitutes: List[str]
    answer: str
