from __future__ import annotations
import os
from typing import Any
from langchain_upstage import ChatUpstage
from app.core.config import settings
from .state import AgentState
from langchain_core.messages import HumanMessage, SystemMessage
from chromadb.utils import embedding_functions
from app.tools.vector_store import get_collection
from app.prompts.prompts import (
    ANSWER_GENERATION_SYSTEM_PROMPT,
    ANSWER_MONTH_DIFF_SUFFIX,
    ANSWER_NO_DATA,
    ANSWER_PRICE_LINE,
    ANSWER_PRICE_WITH_AMOUNT_LINE,
    ANSWER_SUBSTITUTE_LINE,
    ANSWER_UNSUPPORTED_LINE,
    ANSWER_WEEK_DIFF_SUFFIX,
    KNOWLEDGE_STUB_RESPONSE,
    OFFTOPIC_RESPONSE,
    ANSWER_GENERATION_SYSTEM_PROMPT
)
from app.tools.judge import parse_price

from .state import AgentState

_UNSUPPORTED_STATUS = "미지원"


def _get_llm() -> ChatUpstage:
    return ChatUpstage(
        api_key=settings.upstage_api_key,
        model=settings.llm_model,
        timeout=30,
        max_retries=2,
    )

import chromadb


# 비쌈 판정 시에만 hybrid 경로에서 대체품 검색으로 분기 (judge_price 결과 기준)
_EXPENSIVE_STATUS = "비쌈"
_N_SUBSTITUTES = 3
CHROMA_DB_PATH = "./data/chroma_db"
COLLECTION_NAME = "all_food_products"
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")
korean_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL_NAME)

def _get_llm() -> ChatUpstage:
    return ChatUpstage(
        api_key=settings.upstage_api_key,
        model=settings.llm_model,
        timeout=30,
        max_retries=2,
    )
llm = _get_llm()


def search_knowledge_node(state: AgentState) -> dict[str, Any]:
    """ChromaDB RAG 연동 전 임시 stub.

    팀원의 app/tools/substitute.py 구현이 끝나면 그 함수 호출로 교체 예정.
    """
    items = state.get("items", [])
    item = items[0] if items else "해당 품목"
    return {"knowledge_result": KNOWLEDGE_STUB_RESPONSE.format(item=item)}


def search_substitute_node(state: AgentState) -> dict[str, Any]:
    """비쌈으로 판정된 품목에 대해 ChromaDB에서 비슷한 품목 3개를 검색."""
    judgments = state.get("judgment", [])
    expensive_items = [
        j["item_name"] for j in judgments if j.get("status") == _EXPENSIVE_STATUS
    ]

    if not expensive_items:
        return {"substitutes": []}

    query = expensive_items[0]  # 비쌈 품목 중 첫 번째 기준으로 검색

    try:
        collection = get_collection()
    except Exception:
        return {"substitutes": []}

    # 자기 자신이 걸러질 걸 대비해 여유 있게 가져온다
    results = collection.query(
        query_texts=[query],
        n_results=_N_SUBSTITUTES + 5,
        where={"source": "kamis"},
        include=["documents", "metadatas"],
    )

    substitutes: list[str] = []
    for document, meta in zip(
        results["documents"][0],
        results["metadatas"][0],
    ):
        original_name = (meta or {}).get("name")
        name = original_name or document

        # 검색어 자기 자신(설명이든 원래 이름이든)과 완전히 일치하면 제외
        if document == query or original_name == query:
            continue
        if name in substitutes:
            continue

        substitutes.append(name)
        if len(substitutes) >= _N_SUBSTITUTES:
            break
    return {"substitutes": substitutes}


def _template_answer(judgments: list[dict], substitutes: list[str]) -> str:
    """LLM 호출 실패 시 사용하는 고정 템플릿 답변."""
    lines = []
    for j in judgments:
        if j["status"] == _UNSUPPORTED_STATUS:
            lines.append(ANSWER_UNSUPPORTED_LINE.format(item=j["item_name"]))
            continue
        sign = "+" if j["diff_pct"] >= 0 else ""
        if parse_price(j.get("today_price", "-")) is not None:
            line = ANSWER_PRICE_WITH_AMOUNT_LINE.format(
                item=j["item_name"], price=j["today_price"], unit=j.get("unit", "-"),
                sign=sign, diff=j["diff_pct"], status=j["status"],
            )
        else:
            line = ANSWER_PRICE_LINE.format(item=j["item_name"], sign=sign, diff=j["diff_pct"], status=j["status"])
        week_diff = j.get("week_diff_pct")
        if week_diff is not None:
            line += ANSWER_WEEK_DIFF_SUFFIX.format(sign="+" if week_diff >= 0 else "", diff=week_diff)
        month_diff = j.get("month_diff_pct")
        if month_diff is not None:
            line += ANSWER_MONTH_DIFF_SUFFIX.format(sign="+" if month_diff >= 0 else "", diff=month_diff)
        lines.append(line)
    if substitutes:
        lines.append(ANSWER_SUBSTITUTE_LINE.format(substitutes=", ".join(substitutes)))
    return "\n".join(lines)


def _price_facts(judgments: list[dict], substitutes: list[str]) -> str:
    """LLM에게 근거로 넘겨줄 판정 데이터 — 이 안에 없는 수치는 LLM이 지어내면 안 됨."""
    lines = []
    for j in judgments:
        if j["status"] == _UNSUPPORTED_STATUS:
            lines.append(f"- {j['item_name']}: 가격 데이터 없음(지원하지 않는 품목 — 가격·판정을 지어내지 말 것)")
            continue
        sign = "+" if j["diff_pct"] >= 0 else ""
        if parse_price(j.get("today_price", "-")) is not None:
            line = f"- {j['item_name']}: 현재가 {j['today_price']}원/{j.get('unit', '-')}, 평년 대비 {sign}{j['diff_pct']}% ({j['status']})"
        else:
            line = f"- {j['item_name']}: 평년 대비 {sign}{j['diff_pct']}% ({j['status']}) (현재가 데이터 없음 — 금액을 지어내지 말 것)"
        week_diff = j.get("week_diff_pct")
        if week_diff is not None:
            wsign = "+" if week_diff >= 0 else ""
            line += f", 1주일 전 대비 {wsign}{week_diff}%"
        month_diff = j.get("month_diff_pct")
        if month_diff is not None:
            msign = "+" if month_diff >= 0 else ""
            line += f", 1개월 전 대비 {msign}{month_diff}%"
        lines.append(line)
    if substitutes:
        lines.append(f"- 대체 가능 품목: {', '.join(substitutes)}")
    else:
        # 명시적으로 "없음"을 알려주지 않으면 LLM이 자체적으로 대체품을 지어내는 경우가 있어 방지
        lines.append("- 대체 품목 데이터: 없음 (대체품을 절대 언급하거나 추천하지 말 것)")
    return "\n".join(lines)


async def generate_answer_node(state: AgentState) -> dict[str, Any]:
    """판정 결과를 LLM으로 자연어 답변 생성 — 실패 시 고정 템플릿으로 폴백."""
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
    print(f"[generate_answer_node] substitutes: {substitutes}")
    if substitutes:
        lines.append(ANSWER_SUBSTITUTE_LINE.format(substitutes=", ".join(substitutes)))
    context_parts = [
        f"사용자 질문: {state.get('user_query', '')}",
        "가격 판정 결과:",
        "\n".join(lines),
    ]
    
    context = "\n".join(context_parts)

    response = llm.invoke(
        [
            SystemMessage(content=ANSWER_GENERATION_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ]
    )
    return {"answer": response.content}


def generate_offtopic_node(state: AgentState) -> dict[str, Any]:
    return {"answer": OFFTOPIC_RESPONSE}
