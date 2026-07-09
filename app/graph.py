from __future__ import annotations
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.router import router_node
from app.core.state import AgentState
from app.prompts.prompts import ANSWER_NO_DATA, ANSWER_PRICE_LINE, OFFTOPIC_RESPONSE
from app.tools.judge import judge_price_node
from app.tools.kamis import get_raw_price_node


def generate_answer_node(state: AgentState) -> dict[str, Any]:
    """판정 결과를 자연어 문장으로 조합 — Day3에 SSE + LLM 호출로 교체."""
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

    return {"answer": "\n".join(lines)}


def generate_offtopic_node(state: AgentState) -> dict[str, Any]:
    return {"answer": OFFTOPIC_RESPONSE}


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
