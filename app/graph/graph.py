from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import generate_answer_node, generate_offtopic_node
from .router import router_node
from .state import AgentState
from app.tools.judge import judge_price_node
from app.tools.kamis import get_raw_price_node


def _route_decision(state: AgentState) -> str:
    return state.get("route", "off-topic")


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("router", router_node)
    graph.add_node("get_raw_price", get_raw_price_node)
    graph.add_node("judge_price", judge_price_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("generate_offtopic", generate_offtopic_node)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        _route_decision,
        {
            "price": "get_raw_price",
            "off-topic": "generate_offtopic",
        },
    )
    graph.add_edge("get_raw_price", "judge_price")
    graph.add_edge("judge_price", "generate_answer")
    graph.add_edge("generate_answer", END)
    graph.add_edge("generate_offtopic", END)

    return graph


compiled_graph = build_graph().compile()
