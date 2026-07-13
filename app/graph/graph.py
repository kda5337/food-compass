from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.tools.judge import judge_price_node
from app.tools.kamis import get_raw_price_node

from .nodes import (
    compare_items_node,
    generate_answer_node,
    generate_offtopic_node,
    resolve_processed_items_node,
    search_knowledge_node,
    search_substitute_node,
)
from .router import router_node
from .state import AgentState

_EXPENSIVE_STATUS = "비쌈"


def _route_decision(state: AgentState) -> str:
    return state.get("route", "off-topic")


def _post_resolve_decision(state: AgentState) -> str:
    """[시나리오 1] 원물(kamis) + 가공식품(price_gokr) 2개 품목이 모두 조회됐으면
    비교 플로우로, 그 외엔 기존 judge_price 플로우로 분기."""
    price_data = state.get("price_data", [])
    if len(price_data) == 2:
        sources = {item.get("source") for item in price_data}
        if sources == {"kamis", "price_gokr"} and all(item.get("found") for item in price_data):
            return "compare"
    return "judge"


def _post_judge_decision(state: AgentState) -> str:
    """hybrid 경로에서만 비쌈 판정 시 대체품 검색으로 분기, 그 외엔 바로 답변 생성."""
    #if state.get("route") != "hybrid":
    #    return "answer"
    judgments = state.get("judgment", [])
    if any(j.get("status") == _EXPENSIVE_STATUS for j in judgments):
        return "substitute"
    return "answer"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node("get_raw_price", get_raw_price_node)
    graph.add_node("resolve_processed_items", resolve_processed_items_node)
    graph.add_node("compare_items", compare_items_node)
    graph.add_node("judge_price", judge_price_node)
    graph.add_node("search_knowledge", search_knowledge_node)
    graph.add_node("search_substitute", search_substitute_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("generate_offtopic", generate_offtopic_node)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        _route_decision,
        {
            "price": "get_raw_price",
            "hybrid": "get_raw_price",
            "knowledge": "search_knowledge",
            "off-topic": "generate_offtopic",
        },
    )
    # [시나리오 1] get_raw_price(KAMIS) 이후 항상 resolve_processed_items를 거침 —
    # 일반적인 단일/다중 원물 조회는 이 노드가 그대로 통과시켜(price_data 변경 없음)
    # 기존 judge_price 흐름과 동일하게 동작하고, "원물 1개 + 가공식품 1개" 조합일 때만
    # compare_items로 분기됨.
    graph.add_edge("get_raw_price", "resolve_processed_items")
    graph.add_conditional_edges(
        "resolve_processed_items",
        _post_resolve_decision,
        {
            "compare": "compare_items",
            "judge": "judge_price",
        },
    )
    graph.add_edge("compare_items", "generate_answer")
    graph.add_conditional_edges(
        "judge_price",
        _post_judge_decision,
        {
            "substitute": "search_substitute",
            "answer": "generate_answer",
        },
    )
    graph.add_edge("search_substitute", "generate_answer")
    graph.add_edge("search_knowledge", "generate_answer")
    graph.add_edge("generate_answer", END)
    graph.add_edge("generate_offtopic", END)

    return graph


compiled_graph = build_graph().compile()
