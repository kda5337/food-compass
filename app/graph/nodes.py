from __future__ import annotations
from typing import Any

from .state import AgentState
from app.prompts.prompts import ANSWER_NO_DATA, ANSWER_PRICE_LINE, OFFTOPIC_RESPONSE


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
