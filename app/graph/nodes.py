from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_upstage import ChatUpstage

from app.core.config import settings
from app.prompts.prompts import (
    ANSWER_GENERATION_SYSTEM_PROMPT,
    ANSWER_MONTH_DIFF_SUFFIX,
    ANSWER_NO_DATA,
    ANSWER_PRICE_LINE,
    ANSWER_PRICE_WITH_AMOUNT_AS_OF_LINE,
    ANSWER_PRICE_WITH_AMOUNT_LINE,
    ANSWER_SUBSTITUTE_LINE,
    ANSWER_UNSUPPORTED_LINE,
    ANSWER_WEEK_DIFF_SUFFIX,
    KNOWLEDGE_GENERATION_SYSTEM_PROMPT,
    KNOWLEDGE_STUB_RESPONSE,
    OFFTOPIC_RESPONSE,
)
from app.tools.judge import parse_price
from app.tools.vector_store import get_collection

from .state import AgentState

_UNSUPPORTED_STATUS = "미지원"
# 비쌈 판정 시에만 hybrid 경로에서 대체품 검색으로 분기 (judge_price 결과 기준)
_EXPENSIVE_STATUS = "비쌈"
_N_SUBSTITUTES = 3


def _get_llm() -> ChatUpstage:
    return ChatUpstage(
        api_key=settings.upstage_api_key,
        model=settings.llm_model,
        timeout=30,
        max_retries=2,
    )
llm = _get_llm()


def search_knowledge_node(state: AgentState) -> dict[str, Any]:
    """가격과 무관한 지식(보관법·대체품·제철정보 등) 질문에 대한 답변 생성."""
    items = state.get("items", [])
    item = items[0] if items else "해당 품목"
    user_query = state.get("user_query", "")

    context = f"사용자 질문: {user_query}\n관련 품목: {item}"

    try:
        response = llm.invoke(
            [
                SystemMessage(content=KNOWLEDGE_GENERATION_SYSTEM_PROMPT),
                HumanMessage(content=context),
            ]
        )
        return {"knowledge_result": response.content}
    except Exception:
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
        strict=True,
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
            price_as_of = j.get("price_as_of")
            # [2026-07-14 추가] _price_facts()와 동일한 이유로, fallback 값을 쓴 경우
            # "N일 전 기준" 문구가 붙은 별도 템플릿 사용
            if price_as_of not in (None, "당일"):
                line = ANSWER_PRICE_WITH_AMOUNT_AS_OF_LINE.format(
                    item=j["item_name"], as_of=price_as_of, price=j["today_price"], unit=j.get("unit", "-"),
                    sign=sign, diff=j["diff_pct"], status=j["status"],
                )
            else:
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
        today_price = j.get("today_price")
        if today_price is not None:
            # [2026-07-14 추가] today_price가 당일가 결측으로 며칠 전 값(dpr2~dpr5 fallback)을
            # 대신 쓴 경우, "현재가"라고만 하면 사용자가 오늘 가격으로 오해할 수 있어
            # price_as_of("1주일전" 등)를 그대로 문구에 노출 — LLM이 마치 당일가인 것처럼
            # 말하지 않도록 데이터 단계에서부터 명시.
            price_as_of = j.get("price_as_of")
            price_label = "현재가" if price_as_of in (None, "당일") else f"{price_as_of} 가격(당일 데이터 미반영)"
            line = f"- {j['item_name']}: {price_label} {j['today_price']}원/{j.get('unit', '-')}, 평년 대비 {sign}{j['diff_pct']}% ({j['status']})"
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

    substitutes = state.get("substitutes") or []
    print(f"[generate_answer_node] substitutes: {substitutes}")

    # [2026-07-14 수정] 기존엔 여기서 ANSWER_PRICE_LINE만으로 직접 lines를 만들어서
    # today_price/unit(실제 가격 금액), week/month 대비 추세가 LLM 컨텍스트에 전혀 안 들어가고 있었음
    # (판정 상태 문구만 들어감 — "가격 정보가 답변에 안 나온다"는 문제의 원인).
    # 이미 있던 _price_facts()가 정확히 이 데이터를 다 채워서 만들어주는 함수인데 호출이 안 되고
    # 있었던 것 — 이제 그대로 재사용.
    context_parts = [
        f"사용자 질문: {state.get('user_query', '')}",
        "가격 판정 결과:",
        _price_facts(judgments, substitutes),
    ]
    context = "\n".join(context_parts)

    try:
        response = llm.invoke(
            [
                SystemMessage(content=ANSWER_GENERATION_SYSTEM_PROMPT),
                HumanMessage(content=context),
            ]
        )
        answer = response.content
    except Exception as e:
        # 함수 docstring에 원래 "실패 시 고정 템플릿으로 폴백"이라고 적혀 있었는데
        # 실제로는 이 폴백이 연결돼 있지 않았음 — _template_answer()도 같이 살려서 연결함.
        print(f"[generate_answer_node] LLM 호출 실패, 템플릿 답변으로 폴백: {e!r}")
        answer = _template_answer(judgments, substitutes)

    return {"answer": answer}


def generate_offtopic_node(state: AgentState) -> dict[str, Any]:
    return {"answer": OFFTOPIC_RESPONSE}
