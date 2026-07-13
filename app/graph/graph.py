from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    generate_answer_node,
    generate_offtopic_node,
    search_knowledge_node,
    search_substitute_node,
)
from .router import router_node
from .state import AgentState
from app.tools.judge import judge_price_node
from app.tools.kamis import get_raw_price_node

_EXPENSIVE_STATUS = "비쌈"


def _route_decision(state: AgentState) -> str:
    return state.get("route", "off-topic")


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
    graph.add_edge("get_raw_price", "judge_price")
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
