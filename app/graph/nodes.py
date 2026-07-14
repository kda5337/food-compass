from __future__ import annotations

import re
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
    ANSWER_PROCESSED_UNSUPPORTED_LINE,
    ANSWER_SUBSTITUTE_LINE,
    ANSWER_UNSUPPORTED_LINE,
    COMMON_ANSWER_SYSTEM_PROMPT,
    COMPARISON_ANSWER_SYSTEM_PROMPT,
    KNOWLEDGE_GENERATION_SYSTEM_PROMPT,
    KNOWLEDGE_STUB_RESPONSE,
    OFFTOPIC_RESPONSE,
    PROCESSED_PRICE_ANSWER_SYSTEM_PROMPT,
)
from app.tools.item_alias import resolve_processed_alias
from app.tools.judge import parse_price  # noqa
from app.tools.kamis import LIVESTOCK_ITEMS
from app.tools.normalize import rice_price_per_bowl
from app.tools.price_gokr_snapshot import get_processed_price, search_processed_items
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


# [2026-07-14 추가] 프롬프트로 "마크다운 서식 금지"를 지시해도 LLM이 가끔 **굵게** 같은
# 마크다운 강조 문법을 흘리는 경우가 있어(실제로 가공식품 답변에서 관측됨), 프롬프트 지시만으론
# 보장이 안 돼서 코드에서 직접 제거 — 채팅 UI가 마크다운을 렌더링하지 않아 "**"이 그대로
# 노출되는 문제를 막기 위한 하드 개런티.
_MARKDOWN_EMPHASIS_RE = re.compile(r"\*\*|__")


def _invoke_with_prompts(specific_prompt: str, context: str) -> str:
    """공통 프롬프트(COMMON_ANSWER_SYSTEM_PROMPT) + 노드별 프롬프트를 각각 별도의
    SystemMessage로 함께 전달 — 페르소나·어투·이모지 개수 등 공통 원칙은 한 곳에서만
    관리하고, 노드별 프롬프트에는 그 노드만의 고유 규칙만 남기기 위함(2026-07-14 프롬프트 세분화).
    반환 전 마크다운 강조 문법(**, __)을 제거해 순수 텍스트만 남긴다."""
    response = llm.invoke(
        [
            SystemMessage(content=COMMON_ANSWER_SYSTEM_PROMPT),
            SystemMessage(content=specific_prompt),
            HumanMessage(content=context),
        ]
    )
    content = response.content
    text = content if isinstance(content, str) else str(content)
    return _MARKDOWN_EMPHASIS_RE.sub("", text)


def search_knowledge_node(state: AgentState) -> dict[str, Any]:
    """가격과 무관한 지식(보관법·대체품·제철정보 등) 질문에 대한 답변 생성."""
    items = state.get("items", [])
    item = items[0] if items else "해당 품목"
    user_query = state.get("user_query", "")

    context = f"사용자 질문: {user_query}\n관련 품목: {item}"

    try:
        answer = _invoke_with_prompts(KNOWLEDGE_GENERATION_SYSTEM_PROMPT, context)
        return {"knowledge_result": answer}
    except Exception:
        return {"knowledge_result": KNOWLEDGE_STUB_RESPONSE.format(item=item)}


def _substitute_query_name(item_name: str) -> str:
    """축산물은 "돼지 갈비"처럼 "품목 부위" 합성 이름으로 판정되는데, 이 이름 그대로
    대체품을 검색하면 기존 자기 자신 제외 로직(완전 일치 검사)이 "돼지 갈비" != "돼지"라
    못 걸러내서 대체품 후보에 "돼지" 자기 자신이 나오는 문제가 있었음(2026-07-15 확인) —
    합성 이름이면 기본 품목명만 뽑아 검색하고, 그러면 기존 완전 일치 제외 로직이 정상 동작함."""
    first_token = item_name.split(" ", 1)[0]
    return first_token if first_token in LIVESTOCK_ITEMS else item_name


def search_substitute_node(state: AgentState) -> dict[str, Any]:
    """비쌈으로 판정된 품목에 대해 ChromaDB에서 비슷한 품목 3개를 검색."""
    judgments = state.get("judgment", [])
    expensive_items = [
        j["item_name"] for j in judgments if j.get("status") == _EXPENSIVE_STATUS
    ]

    if not expensive_items:
        return {"substitutes": []}

    query = _substitute_query_name(expensive_items[0])  # 비쌈 품목 중 첫 번째 기준으로 검색

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


def resolve_processed_items_node(state: AgentState) -> dict[str, Any]:
    """[시나리오 1: 쌀 vs 즉석밥] KAMIS에 없는 품목이 원물+가공식품 2개 조합의
    가공식품 쪽으로 보이면 참가격(price_gokr)으로 재조회.

    "이 품목이 원물인지 가공식품인지"를 LLM에게 분류시키지 않고, 이미 있는
    found 플래그(KAMIS 조회 결과)만으로 판별 — 정확히 "품목 2개, 하나는 KAMIS에서
    찾음 + 다른 하나는 못 찾음" 조합일 때만 참가격 폴백을 시도한다(스코프 제한:
    참가격 단독 조회나 3개 이상 품목 조합은 이번 시나리오 1 구현 범위 밖).
    """
    price_data = state.get("price_data", [])
    if len(price_data) != 2:
        return {}

    found_items = [item for item in price_data if item.get("found")]
    not_found_items = [item for item in price_data if not item.get("found")]
    if len(found_items) != 1 or len(not_found_items) != 1:
        return {}

    target = not_found_items[0]
    good_name = resolve_processed_alias(target["item_name"])
    if not good_name:
        return {}

    try:
        processed = get_processed_price(good_name)
    except Exception as e:
        print(f"[resolve_processed_items] 참가격 DB 조회 실패: {e}")
        return {}
    if not processed:
        return {}

    updated_price_data = []
    for item in price_data:
        if item is target:
            updated_price_data.append(
                {
                    "item_name": item["item_name"],
                    "unit": "1공기(210g)",
                    "found": True,
                    "source": "price_gokr",
                    "avg_price": processed["avg_price"],
                    "sample_count": processed["sample_count"],
                    "inspect_day": processed["inspect_day"],
                }
            )
        else:
            updated_price_data.append({**item, "source": "kamis"})
    return {"price_data": updated_price_data}


def compare_items_node(state: AgentState) -> dict[str, Any]:
    """[시나리오 1] 원물(쌀) 밥 1공기 환산가와 가공식품(즉석밥) 1개(1공기) 평균가를
    비교해서 어느 쪽이 더 경제적인지 계산 — 판정(judge_price)이 아니라 두 품목 간
    비교라서 별도 로직으로 처리."""
    price_data = state.get("price_data", [])
    kamis_item = next((i for i in price_data if i.get("source") == "kamis"), None)
    gokr_item = next((i for i in price_data if i.get("source") == "price_gokr"), None)
    if kamis_item is None or gokr_item is None:
        return {"comparison": None}

    raw_price = parse_price(kamis_item.get("dpr1", "-"))
    raw_per_bowl = (
        rice_price_per_bowl(raw_price, kamis_item.get("unit")) if raw_price is not None else None
    )
    processed_per_bowl = gokr_item.get("avg_price")

    if raw_per_bowl is None or processed_per_bowl is None:
        return {"comparison": None}

    cheaper_item = kamis_item["item_name"] if raw_per_bowl < processed_per_bowl else gokr_item["item_name"]
    lower, higher = sorted([raw_per_bowl, processed_per_bowl])
    diff_pct = round((higher - lower) / higher * 100, 1)
    ratio = round(higher / lower, 1)

    return {
        "comparison": {
            "raw_item": kamis_item["item_name"],
            "raw_price_per_bowl": raw_per_bowl,
            "raw_price_as_of": kamis_item.get("price_as_of"),
            "processed_item": gokr_item["item_name"],
            "processed_price_per_bowl": processed_per_bowl,
            "cheaper_item": cheaper_item,
            "diff_pct": diff_pct,
            "ratio": ratio,
        }
    }


def search_processed_price_node(state: AgentState) -> dict[str, Any]:
    """[가공식품 단독 조회] KAMIS에 없는 품목(예: "참치캔")을 참가격(price_gokr)에서
    부분일치로 검색해 매칭되는 상품 전부의 평균가를 조회 — 비쌈/적정 판정은 하지 않음.

    ChromaDB 유사도 검색으로 상품 1개만 콕 집는 방식도 검토했으나, "소"를 검색했을 때
    "천일염"이 나왔던 것처럼 엉뚱한 상품이 잘못 골라질 위험이 있어(2026-07-14 사용자 확인)
    매칭되는 상품을 전부 보여주는 방식을 택함 — 잘못된 단일 매칭 자체가 발생할 수 없음.
    """
    price_data = state.get("price_data", [])
    results = []
    for item in price_data:
        matches = search_processed_items(item["item_name"])
        products = []
        for match in matches:
            price_info = get_processed_price(match["good_name"])
            if price_info:
                products.append(
                    {
                        "good_name": match["good_name"],
                        "avg_price": price_info["avg_price"],
                        "sample_count": price_info["sample_count"],
                    }
                )
        results.append(
            {
                "item_name": item["item_name"],
                "found": bool(products),
                "products": products,
            }
        )
    return {"processed_prices": results}


def _processed_price_facts(results: list[dict]) -> str:
    """가공식품 단독 조회 답변 생성 LLM에게 넘겨줄 근거 데이터 — 이 안에 없는 수치는 지어내면 안 됨."""
    lines = []
    for r in results:
        if not r["found"]:
            lines.append(f"- {r['item_name']}: 가격 데이터 없음(지원하지 않는 품목 — 가격을 지어내지 말 것)")
            continue
        lines.append(f"- {r['item_name']} 검색 결과 (판정 없이 평균가만 제공):")
        for p in r["products"]:
            lines.append(f"  - {p['good_name']}: 평균 {p['avg_price']}원 (매장 {p['sample_count']}곳 기준)")
    return "\n".join(lines)


def _template_processed_price_answer(results: list[dict]) -> str:
    """가공식품 단독 조회 LLM 호출 실패 시 사용하는 고정 템플릿."""
    lines = []
    for r in results:
        if not r["found"]:
            lines.append(ANSWER_PROCESSED_UNSUPPORTED_LINE.format(item=r["item_name"]))
            continue
        product_lines = ", ".join(f"{p['good_name']} 평균 {p['avg_price']}원" for p in r["products"])
        lines.append(f"{r['item_name']}: {product_lines}")
    return "\n".join(lines)


def _product_core_name(good_name: str) -> str:
    """"동원참치 라이트스탠다드(150g)" -> "동원참치 라이트스탠다드" — 괄호 안 규격 표기를 뗀 핵심명.

    LLM이 답변을 자연스럽게 쓰면서 "(150g)" -> "150g"처럼 괄호를 없애거나 띄어쓰기를
    살짝 바꾸는 경우가 흔해서(실제로 관측함), 전체 상품명을 그대로 문자열 대조하면
    정상 답변인데도 불필요하게 폴백되는 문제가 있어 핵심명만 비교.
    """
    return re.sub(r"\(.*\)\s*$", "", good_name).strip()


def _processed_price_answer_covers_results(answer: str, results: list[dict]) -> bool:
    """답변이 실제 조회 결과를 반영하고 있는지 확인.

    [2026-07-14 확인] r["item_name"]은 사용자가 부른 원문 그대로(예: "참치캔")라, LLM이
    매칭된 실제 상품명(예: "동원참치 라이트스탠다드")으로 자연스럽게 답하면 원문 "참치캔"이
    답변에 안 남는 경우가 많음 — 이건 정상 답변인데 원문 문자열만 확인하면 불필요하게
    폴백되므로, "찾음" 케이스는 매칭된 상품명(핵심명 기준) 중 하나라도 있는지로,
    "못 찾음" 케이스만 item_name으로 확인.
    """
    for r in results:
        if r["found"]:
            if any(_product_core_name(p["good_name"]) in answer for p in r["products"]):
                return True
        elif r["item_name"] in answer:
            return True
    return False


def _generate_processed_price_answer(results: list[dict], user_query: str) -> str:
    context = f"사용자 질문: {user_query}\n가공식품 가격 조회 결과:\n{_processed_price_facts(results)}"
    try:
        answer = _invoke_with_prompts(PROCESSED_PRICE_ANSWER_SYSTEM_PROMPT, context)
        if not _processed_price_answer_covers_results(answer, results):
            print(f"[generate_answer_node] 가공식품 답변에 조회 결과 누락, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_processed_price_answer(results)
    except Exception as e:
        print(f"[generate_answer_node] 가공식품 LLM 호출 실패, 템플릿 답변으로 폴백: {e!r}")
        answer = _template_processed_price_answer(results)
    return answer


def _comparison_facts(comparison: dict) -> str:
    """비교형 답변 생성 LLM에게 넘겨줄 근거 데이터 — 이 안에 없는 수치는 지어내면 안 됨."""
    raw_as_of = comparison.get("raw_price_as_of")
    as_of_note = f"({raw_as_of} 기준)" if raw_as_of not in (None, "당일") else ""
    return (
        f"- {comparison['raw_item']}{as_of_note}: 밥 1공기(마른 쌀 90g = 지어진 밥 210g 기준)당 "
        f"약 {comparison['raw_price_per_bowl']}원\n"
        f"- {comparison['processed_item']}: 1개(1공기, 210g)당 약 {comparison['processed_price_per_bowl']}원\n"
        f"- 결론: {comparison['cheaper_item']}이(가) 약 {comparison['diff_pct']}%"
        f"({comparison['ratio']}배) 더 저렴함\n"
        "- 환산 기준(반드시 답변에 한 문장으로 그대로 밝힐 것): "
        "마른 쌀 90g = 지어진 밥 210g = 밥 1공기 = 즉석밥 1개"
    )


def _template_comparison_answer(comparison: dict) -> str:
    """비교형 답변 LLM 호출 실패 시 사용하는 고정 템플릿."""
    return (
        f"{comparison['raw_item']} 밥 1공기(마른 쌀 90g→지어진 밥 210g 기준)는 약 "
        f"{comparison['raw_price_per_bowl']}원, {comparison['processed_item']} 1개(1공기)는 약 "
        f"{comparison['processed_price_per_bowl']}원이에요. "
        f"{comparison['cheaper_item']} 쪽이 약 {comparison['diff_pct']}%({comparison['ratio']}배) 더 저렴해요."
    )


def _generate_comparison_answer(comparison: dict, user_query: str) -> str:
    context = f"사용자 질문: {user_query}\n비교 데이터:\n{_comparison_facts(comparison)}"
    try:
        answer = _invoke_with_prompts(COMPARISON_ANSWER_SYSTEM_PROMPT, context)
        if comparison["raw_item"] not in answer or comparison["processed_item"] not in answer:
            print(f"[generate_answer_node] 비교형 답변에 품목명 누락, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_comparison_answer(comparison)
    except Exception as e:
        print(f"[generate_answer_node] 비교형 LLM 호출 실패, 템플릿 답변으로 폴백: {e!r}")
        answer = _template_comparison_answer(comparison)
    return answer


def _template_answer(judgments: list[dict], substitutes: list[str]) -> str:
    """LLM 호출 실패 시 사용하는 고정 템플릿 답변."""
    lines = []
    for j in judgments:
        if j["status"] == _UNSUPPORTED_STATUS:
            lines.append(ANSWER_UNSUPPORTED_LINE.format(item=j["item_name"]))
            continue
        sign = "+" if j["diff_pct"] >= 0 else ""
        today_price = j.get("today_price")
        if today_price is not None:
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
        month_diff = j.get("month_diff_pct")
        if month_diff is not None:
            line += ANSWER_MONTH_DIFF_SUFFIX.format(sign="+" if month_diff >= 0 else "", diff=month_diff)
        lines.append(line)
    if substitutes:
        lines.append(ANSWER_SUBSTITUTE_LINE.format(substitutes=", ".join(substitutes)))
    return "\n".join(lines)


# [2026-07-14 추가] "오이 지금 비싸?"를 실제로 5번 호출해보니 status="쌈"(저렴함)인데도
# 5번 중 4번이 "지금은 조금 비싼 편이에요!"로 시작하는 걸 확인함 — 프롬프트로 "판정 결과를
# 그대로 따르라"고 지시해도 시작 문장 선택 자체를 LLM의 자유 판단에 맡겨두면 diff_pct의
# 부호를 잘못 해석하는 등으로 실제 판정과 정반대로 답할 위험이 큼(재현 확률 80%로 확인).
# status는 이미 코드에서 확정된 값이라 LLM이 다시 판단할 이유가 없으므로, 시작 문장을
# 코드에서 직접 골라 "반드시 이 문장 그대로 시작할 것"으로 강제하고(아래 _select_opening_line),
# 그래도 어길 경우를 대비해 _opening_conflicts_with_status()로 한 번 더 검증한다.
_STATUS_OPENING_LINES = {
    "비쌈": "지금은 조금 비싼 편이에요!",
    "적정": "요즘 가격은 무난한 편이에요.",
    "쌈": "요즘 가격이 괜찮네요!!",
}
_EXPENSIVE_SIGNAL_WORDS = ("비싸", "비쌈")
_CHEAP_SIGNAL_WORDS = ("저렴", "괜찮", "무난")


def _primary_status(judgments: list[dict]) -> str | None:
    """미지원이 아닌 첫 품목의 판정 상태 — 시작 문장 선택 기준(다품목이면 첫 번째 기준)."""
    for j in judgments:
        if j["status"] != _UNSUPPORTED_STATUS:
            return j["status"]
    return None


def _select_opening_line(judgments: list[dict]) -> str | None:
    status = _primary_status(judgments)
    return _STATUS_OPENING_LINES.get(status) if status else None


def _opening_conflicts_with_status(answer: str, status: str | None) -> bool:
    """답변 첫 문장의 어조가 실제 판정(status)과 반대인지 확인 — "오이 지금 비싸?" 재현
    버그(status=쌈인데 "비싼 편이에요!"로 시작)를 잡아내기 위한 하드 개런티."""
    if status is None:
        return False
    first_sentence = re.split(r"[.!\n]", answer, maxsplit=1)[0]
    has_expensive = any(w in first_sentence for w in _EXPENSIVE_SIGNAL_WORDS)
    has_cheap = any(w in first_sentence for w in _CHEAP_SIGNAL_WORDS)
    if status == "비쌈":
        return has_cheap and not has_expensive
    if status in ("적정", "쌈"):
        return has_expensive and not has_cheap
    return False


# [2026-07-15 추가] 실제 관측: "돼지 갈비" 답변에서 실제 평년 대비 등락률(month_diff_pct)이
# +4.7%인데 LLM이 "167.4% 상승"이라고 답변에 써서 완전히 지어낸 수치가 그대로 나간 것을
# 확인함 — 지금까지의 하드개런티는 품목명 언급/판정 어조만 검증했지 답변에 등장하는
# "숫자 자체"가 실제 데이터와 일치하는지는 전혀 검증하지 않고 있었음. 답변에 등장하는
# 모든 퍼센트 수치가 judgments의 실제 diff_pct/month_diff_pct 값 중 하나와 (반올림 오차
# 허용 범위 내에서) 일치하는지 확인 — 근거 없는 수치가 하나라도 있으면 폴백.
_PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_PERCENT_TOLERANCE = 0.15


def _known_percentage_magnitudes(judgments: list[dict]) -> set[float]:
    """실제 diff_pct/month_diff_pct의 절대값 집합.

    [2026-07-15 확인] 절대값으로만 비교하는 이유 — LLM이 "4.8% 하락"처럼 방향을 부호가
    아니라 단어("하락"/"내려서")로 표현하는 경우가 흔한데, 실데이터로 4번 반복 호출해보니
    이런 정상 답변까지 부호가 다르다는 이유로 오탐돼 매번 폴백되는 걸 확인함(단순 서명 비교는
    과함) — 부호는 무시하고 크기(절대값)만 실제 데이터와 맞는지 확인한다.
    """
    values: set[float] = set()
    for j in judgments:
        for field in ("diff_pct", "month_diff_pct"):
            value = j.get(field)
            if value is not None:
                values.add(round(abs(value), 1))
    return values


def _answer_has_fabricated_percentage(answer: str, judgments: list[dict]) -> bool:
    known_magnitudes = _known_percentage_magnitudes(judgments)
    if not known_magnitudes:
        return False
    for raw in _PERCENT_RE.findall(answer):
        pct = abs(float(raw))
        if not any(abs(pct - k) <= _PERCENT_TOLERANCE for k in known_magnitudes):
            return True
    return False


def _compound_base(item_name: str) -> str | None:
    """"돼지 갈비" -> "돼지". 합성(품목+부위) 이름이 아니면 None."""
    return item_name.split(" ", 1)[0] if " " in item_name else None


_SPECIES_PROXIMITY_WINDOW = 10


def _judgment_mentioned(item_name: str, answer: str, ambiguous_species: bool) -> bool:
    """답변이 이 판정 항목을 실제로 언급하고 있는지 확인.

    [2026-07-15 확인] "돼지 갈비"처럼 "품목 부위" 합성 이름은 LLM이 자연스럽게 "돼지"를
    생략하고 "갈비"라고만 쓰는 경우가 흔해서(문맥상 이미 돼지고기 얘기라 중복 언급을
    피함), 전체 문자열을 그대로 대조하면 정상 답변인데도 불필요하게 템플릿로 폴백되는
    문제가 있었음 — _product_core_name()과 동일한 이유로, 부위명(마지막 토큰)만으로도
    언급된 것으로 인정한다.

    [2026-07-15 코드 리뷰 반영] 단, 이번 판정 목록에 서로 다른 축종(예: 돼지+소)이 함께
    섞여 있으면(ambiguous_species=True) 부위명만으론 어느 축종 얘기인지 모호함 —
    "돼지 갈비" 판정인데 답변엔 "소 갈비"만 있어도 "갈비"만 있으면 잘못 통과해버림.
    처음엔 "품목명(base)도 답변 어딘가에 있으면 통과"로 짰는데, "돼지고기랑 소고기
    가격을 보면, 소 갈비는..."처럼 서두에 "돼지고기"가 언급되고 실제로는 "소 갈비"만
    설명하는 문장에서 여전히 통과해버리는 걸 직접 테스트로 확인함 — 단순 존재 여부가
    아니라, 부위명이 등장하는 바로 그 위치 근처(앞 10자 이내)에 품목명이 실제로 붙어
    있는지까지 확인해야 함. 축종이 하나뿐이면(기존처럼) 부위명만으로 충분.
    """
    if item_name in answer:
        return True
    core = item_name.rsplit(" ", 1)[-1]
    if not ambiguous_species:
        return core in answer
    base = _compound_base(item_name)
    if base is None:
        return core in answer
    for match in re.finditer(re.escape(core), answer):
        window_start = max(0, match.start() - _SPECIES_PROXIMITY_WINDOW)
        if base in answer[window_start : match.start()]:
            return True
    return False


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
            # [2026-07-14 라벨 수정] diff_pct는 실제로 1주일전(dpr3) vs 1개월전(dpr5) 계산이라
            # "평년 대비"가 아니라 "1개월 전 대비"가 맞는 라벨 (계산 자체는 변경 없음)
            line = f"- {j['item_name']}: {price_label} {j['today_price']}원/{j.get('unit', '-')}, 1개월 전 대비 {sign}{j['diff_pct']}% ({j['status']})"
        else:
            line = f"- {j['item_name']}: 1개월 전 대비 {sign}{j['diff_pct']}% ({j['status']}) (현재가 데이터 없음 — 금액을 지어내지 말 것)"
        month_diff = j.get("month_diff_pct")
        if month_diff is not None:
            msign = "+" if month_diff >= 0 else ""
            # month_diff_pct = 1개월전(dpr5) vs 평년(dpr7) → "평년 대비"가 정확한 라벨
            line += f", 평년 대비 {msign}{month_diff}%"
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

    comparison = state.get("comparison")
    if comparison:
        return {"answer": _generate_comparison_answer(comparison, state.get("user_query", ""))}

    processed_prices = state.get("processed_prices")
    if processed_prices:
        return {"answer": _generate_processed_price_answer(processed_prices, state.get("user_query", ""))}

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
    primary_status = _primary_status(judgments)
    opening_line = _select_opening_line(judgments)
    species_bases = {b for j in judgments if (b := _compound_base(j["item_name"])) is not None}
    ambiguous_species = len(species_bases) > 1
    context_parts = [
        f"사용자 질문: {state.get('user_query', '')}",
    ]
    if opening_line:
        context_parts.append(
            f'필수 시작 문장(반드시 이 문장을 그대로 답변의 첫 문장으로 사용할 것 — '
            f'다른 표현으로 바꾸거나 생략하지 말 것): "{opening_line}"'
        )
    context_parts += [
        "가격 판정 결과:",
        _price_facts(judgments, substitutes),
    ]
    context = "\n".join(context_parts)

    try:
        answer = _invoke_with_prompts(ANSWER_GENERATION_SYSTEM_PROMPT, context)
        # [2026-07-14 추가] 프롬프트에 "품목명을 반드시 언급할 것"을 지시해도 LLM이 가끔
        # 생략하는 경우가 있음(자유 문장 생성이라 확률적) — 어떤 품목에 대한 답변인지는
        # 사용자가 항상 알 수 있어야 하는 하드 요구사항이라, 프롬프트 지시만으론 보장이 안 돼서
        # 코드에서 직접 검증하고 누락 시 이미 품목명을 포함하는 템플릿 답변으로 폴백시킴.
        if not any(_judgment_mentioned(j["item_name"], answer, ambiguous_species) for j in judgments):
            print(f"[generate_answer_node] LLM 답변에 품목명 누락, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_answer(judgments, substitutes)
        elif _opening_conflicts_with_status(answer, primary_status):
            # [2026-07-14 추가] "오이 지금 비싸?"(status=쌈)를 5번 호출 중 4번이 "지금은
            # 조금 비싼 편이에요!"로 시작해 실제 판정과 정반대로 답하는 걸 실제로 확인함 —
            # 위에서 시작 문장을 지정해줘도 LLM이 어길 수 있으니 최종 방어선으로 검증.
            print(f"[generate_answer_node] 첫 문장이 판정 결과와 모순, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_answer(judgments, substitutes)
        elif _answer_has_fabricated_percentage(answer, judgments):
            # [2026-07-15 추가] "돼지 갈비" 답변에서 실제 평년 대비 등락률(+4.7%)과 전혀
            # 무관한 "167.4% 상승"이라는 수치가 그대로 나간 걸 실제로 확인함 — 품목명·어조
            # 검증만으론 못 잡는 완전히 지어낸 숫자를 잡기 위한 최종 방어선.
            print(f"[generate_answer_node] 답변에 근거 없는 퍼센트 수치 발견, 템플릿 답변으로 폴백: {answer!r}")
            answer = _template_answer(judgments, substitutes)
    except Exception as e:
        # 함수 docstring에 원래 "실패 시 고정 템플릿으로 폴백"이라고 적혀 있었는데
        # 실제로는 이 폴백이 연결돼 있지 않았음 — _template_answer()도 같이 살려서 연결함.
        print(f"[generate_answer_node] LLM 호출 실패, 템플릿 답변으로 폴백: {e!r}")
        answer = _template_answer(judgments, substitutes)

    return {"answer": answer}


def generate_offtopic_node(state: AgentState) -> dict[str, Any]:
    return {"answer": OFFTOPIC_RESPONSE}
