from __future__ import annotations
from typing import Any

from .state import AgentState
from app.prompts.prompts import (
    ANSWER_NO_DATA,
    ANSWER_PRICE_LINE,
    ANSWER_SUBSTITUTE_LINE,
    KNOWLEDGE_STUB_RESPONSE,
    OFFTOPIC_RESPONSE,
)

# 비쌈 판정 시에만 hybrid 경로에서 대체품 검색으로 분기 (judge_price 결과 기준)
_EXPENSIVE_STATUS = "비쌈"


def search_knowledge_node(state: AgentState) -> dict[str, Any]:
    """ChromaDB RAG 연동 전 임시 stub.

    팀원의 app/tools/substitute.py 구현이 끝나면 그 함수 호출로 교체 예정.
    """
    items = state.get("items", [])
    item = items[0] if items else "해당 품목"
    return {"knowledge_result": KNOWLEDGE_STUB_RESPONSE.format(item=item)}


def search_substitute_node(state: AgentState) -> dict[str, Any]:
    """ChromaDB RAG 연동 전 임시 stub — 대체품 없음으로 응답.

    팀원의 app/tools/substitute.py 구현이 끝나면 그 함수 호출로 교체 예정.
    """
    return {"substitutes": []}


def generate_answer_node(state: AgentState) -> dict[str, Any]:
    """판정 결과를 자연어 문장으로 조합 — Day3에 SSE + LLM 호출로 교체."""
    if state.get("route") == "knowledge":
        return {"answer": state.get("knowledge_result", ANSWER_NO_DATA)}

    judgments = state.get("judgment", [])
    if not judgments:
        return {"answer": ANSWER_NO_DATA}

    lines = []
    for j in judgments:
        item = j["item_name"]
        status = j["status"]
        diff = j["diff_pct"]
        sign = "+" if diff >= 0 else ""
        lines.append(ANSWER_PRICE_LINE.format(item=item, sign=sign, diff=diff, status=status))

    substitutes = state.get("substitutes")
    if substitutes:
        lines.append(ANSWER_SUBSTITUTE_LINE.format(substitutes=", ".join(substitutes)))

    return {"answer": "\n".join(lines)}


def generate_offtopic_node(state: AgentState) -> dict[str, Any]:
    return {"answer": OFFTOPIC_RESPONSE}
