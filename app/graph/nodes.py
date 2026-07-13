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
    ANSWER_NO_DATA,
    ANSWER_PRICE_LINE,
    ANSWER_SUBSTITUTE_LINE,
    KNOWLEDGE_STUB_RESPONSE,
    OFFTOPIC_RESPONSE,
    ANSWER_GENERATION_SYSTEM_PROMPT
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
