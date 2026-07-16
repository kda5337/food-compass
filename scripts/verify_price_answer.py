"""가격 파이프라인 검증 스크립트.

세 가지를 확인한다:
  [0] Supabase price_snapshot에서 조회된 원본 row를 가공 없이 그대로 출력
  [1] 원본 데이터(dpr3/dpr5) -> normalize_price_unit() 정규화 결과가 실제로 올바른 값인지
      (정규화 공식을 이 스크립트에서 독립적으로 재계산해 대조)
  [2] 그 정규화 결과(judge_price 판정값)가 최종 LLM 답변(generate_answer_node)에 언급된
      금액·퍼센트 수치와 실제로 일치하는지 (LLM이 근거 없는 수치를 지어내지 않았는지)

실행:
    $env:PYTHONUTF8=1
    .venv/Scripts/python.exe scripts/verify_price_answer.py [품목명 질문 ...]

인자를 안 주면 기본 샘플 질문들로 실행한다.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.graph.graph import compiled_graph
from app.tools.judge import parse_price

_DEFAULT_QUERIES = ["상추 가격 알려줘", "당근 요즘 비싸?", "사과 시세 어때?"]

_WEIGHT_UNIT_TO_GRAM = {"kg": 1000, "g": 1}
_COUNT_UNITS = {"개", "속", "단", "포기", "마리", "봉", "팩", "모"}
_TARGET_WEIGHT_TO_GRAM = {"100g": 100, "500g": 500, "1kg": 1000}
_SOURCE_UNIT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z가-힣]+)\s*$")

_WON_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*원")
_PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_TOLERANCE = 0.15


def _expected_normalized_price(price: float, source_unit: str | None, target_unit: str | None) -> float | None:
    """app/tools/normalize.py::normalize_price_unit()과 별개로 다시 구현한 기대값 계산.

    이 스크립트만의 독립된 계산식이어야 normalize.py 자체에 있는 회귀를 잡아낼 수 있으므로,
    실제 함수를 호출하는 대신 문서화된 공식(무게 단위는 100g/500g/1kg당 환산, 개수 단위는
    1개당 환산)을 그대로 다시 옮겨 적었다.
    """
    if not source_unit:
        return price
    match = _SOURCE_UNIT_RE.match(source_unit.strip())
    if not match:
        return price
    qty = float(match.group(1))
    unit_label = match.group(2)
    if unit_label in _WEIGHT_UNIT_TO_GRAM:
        total_grams = qty * _WEIGHT_UNIT_TO_GRAM[unit_label]
        if total_grams <= 0:
            return price
        target_grams = _TARGET_WEIGHT_TO_GRAM.get(target_unit, 100)
        return round(price / total_grams * target_grams, 1)
    if unit_label in _COUNT_UNITS:
        if qty <= 0:
            return price
        return round(price / qty, 1)
    return price


def _extract_percentages(text: str) -> list[float]:
    return [abs(float(m)) for m in _PERCENT_RE.findall(text)]


_AVG_PRICE_MARKER = "평년"
_AVG_PRICE_PROXIMITY_WINDOW = 15


def _split_won_amounts_by_avg_mention(text: str) -> tuple[list[float], list[float]]:
    """금액 언급을 "평년" 문맥과 그 외로 분리.

    judge_price()가 실제로 반환하는 normalized_price는 1주일전가 기준 금액뿐이라(평년
    정규화 금액은 계산은 되지만 JudgePriceOutput에 담겨 나오지 않음, app/tools/judge.py
    참고), "평년 가격은 OOO원" 같은 문장의 금액은 known_amounts와 애초에 비교할 근거
    데이터가 없다 — 이 금액은 mismatch 판정에서 제외하고 참고용으로만 별도 표시한다.

    "평년"이 금액 바로 앞/뒤 근처(app/graph/nodes.py의 _SPECIES_PROXIMITY_WINDOW과 동일한
    방식)에 있을 때만 평년 관련으로 판단한다 — 단, 윈도우를 문장 전체가 아니라 같은
    문장 안으로만 한정한다. 두 가지 실제 관측 사례를 모두 처리하기 위함:
      - "...466.0원/100g이에요. 평년 가격보다는..." 처럼 현재가 문장 바로 다음 문장이
        "평년"으로 시작하면, 문장 구분 없이 전체 텍스트에서 윈도우만 적용할 경우 현재가
        금액까지 평년 관련으로 잘못 분류됨 — 문장으로 먼저 나눠 그 문제를 막는다.
      - "현재가 103.0원/100g, ... 평년 대비 -40.3%"처럼 현재가와 평년 언급이 같은 문장에
        함께 있는 템플릿 답변(app/graph/nodes.py의 ANSWER_PRICE_WITH_AMOUNT_LINE +
        ANSWER_MONTH_DIFF_SUFFIX)에서는 문장 단위 판단만으론 현재가 금액까지 평년
        관련으로 잘못 분류됨 — 문장 안에서도 다시 근접도(윈도우)로 좁혀 그 문제를 막는다.
    """
    # 마침표 뒤에 공백이 있을 때만 문장 경계로 봄 — "466.0원"처럼 소수점 뒤에 바로
    # 숫자가 오는 경우(공백 없음)까지 문장으로 쪼개져 금액이 반토막 나는 걸 방지.
    sentences = re.split(r"(?<=[.!])\s+", text)

    checked: list[float] = []
    avg_related: list[float] = []
    for sentence in sentences:
        for match in _WON_RE.finditer(sentence):
            amount = float(match.group(1).replace(",", ""))
            window_start = max(0, match.start() - _AVG_PRICE_PROXIMITY_WINDOW)
            window_end = match.end() + _AVG_PRICE_PROXIMITY_WINDOW
            nearby = sentence[window_start:match.start()] + sentence[match.end():window_end]
            if _AVG_PRICE_MARKER in nearby:
                avg_related.append(amount)
            else:
                checked.append(amount)
    return checked, avg_related


def _close_enough(value: float, candidates: list[float], tolerance: float = _TOLERANCE) -> bool:
    return any(abs(value - c) <= tolerance for c in candidates)


def print_raw_supabase_rows(price_data: list[dict[str, Any]]) -> None:
    """price_data는 app/tools/kamis.py::get_raw_price_node가 get_latest_prices()로
    Supabase price_snapshot에서 조회해온 row를 가공 없이 그대로 담고 있음 —
    가공/정규화 전에 실제로 DB에서 뭘 가져왔는지 그대로 보여준다."""
    print("\n[0] Supabase price_snapshot 원본 조회 결과 (가공 없음)")
    for row in price_data:
        if not row.get("found", True):
            print(f"  - {row.get('item_name')}: DB 미등록 (found=False)")
            continue
        print(f"  - {row.get('item_name')} (kind={row.get('kind_name')}, rank={row.get('rank_name')}):")
        for key in ("unit", "dpr1", "dpr2", "dpr3", "dpr4", "dpr5", "dpr6", "dpr7", "regday", "source", "fetched_at"):
            if key in row:
                print(f"      {key}: {row[key]}")


def check_normalization(price_data: list[dict[str, Any]], judgments: list[dict[str, Any]], target_unit: str | None) -> None:
    print("\n[1] 원본 데이터 -> normalize 검증 (Supabase price_snapshot 기준)")
    judgment_by_item = {j["item_name"]: j for j in judgments}

    for row in price_data:
        item_name = row.get("item_name")
        judgment = judgment_by_item.get(item_name)
        if not row.get("found", True) or judgment is None or judgment.get("status") == "미지원":
            print(f"  - {item_name}: 미지원/데이터 없음 — 건너뜀")
            continue

        raw_last_week = parse_price(row.get("dpr3", "-"))
        source_unit = row.get("unit")
        actual_normalized = judgment.get("today_price")

        if raw_last_week is None:
            print(f"  - {item_name}: dpr3(1주일전가) 결측 — 정규화 대상 아님")
            continue

        expected_normalized = _expected_normalized_price(raw_last_week, source_unit, target_unit)
        ok = (
            expected_normalized is not None
            and actual_normalized is not None
            and abs(expected_normalized - actual_normalized) <= _TOLERANCE
        )
        mark = "OK" if ok else "MISMATCH"
        print(
            f"  - {item_name}: 원본 {raw_last_week}원/{source_unit} -> "
            f"기대값 {expected_normalized}원/{judgment.get('unit')} vs 실제값 {actual_normalized}원/{judgment.get('unit')} "
            f"[{mark}]"
        )


def check_answer_matches_data(answer: str, judgments: list[dict[str, Any]]) -> None:
    print("\n[2] Supabase 기반 판정값 <-> LLM 최종 답변 수치 대조")
    known_amounts = [j["today_price"] for j in judgments if j.get("today_price") is not None]
    known_percentages: list[float] = []
    for j in judgments:
        for field in ("diff_pct", "month_diff_pct"):
            value = j.get(field)
            if value is not None:
                known_percentages.append(abs(value))

    print(f"  판정 근거값: 금액={known_amounts}, 퍼센트={known_percentages}")

    mentioned_amounts, avg_amounts = _split_won_amounts_by_avg_mention(answer)
    mentioned_percentages = _extract_percentages(answer)
    print(f"  답변에 언급된 값: 금액={mentioned_amounts}, 퍼센트={mentioned_percentages}")
    if avg_amounts:
        print(f"  평년 관련 금액 언급(근거 데이터 없어 판정 제외): {avg_amounts}")

    bad_amounts = [a for a in mentioned_amounts if not _close_enough(a, known_amounts)]
    bad_percentages = [p for p in mentioned_percentages if not _close_enough(p, known_percentages)]

    if not bad_amounts and not bad_percentages:
        print("  [OK] 답변에 등장하는 모든 금액·퍼센트가 Supabase 기반 판정값과 일치")
    else:
        if bad_amounts:
            print(f"  [MISMATCH] 근거 없는 금액 언급: {bad_amounts}")
        if bad_percentages:
            print(f"  [MISMATCH] 근거 없는 퍼센트 언급: {bad_percentages}")


async def run_check(user_query: str) -> None:
    print("=" * 70)
    print(f"질문: {user_query!r}")

    result = await compiled_graph.ainvoke({"user_query": user_query})

    route = result.get("route")
    if route != "price" and not result.get("judgment"):
        print(f"  route={route!r} — 가격 판정 경로가 아니라 건너뜀")
        return

    price_data = result.get("price_data", [])
    judgments = result.get("judgment", [])
    answer = result.get("answer", "")
    target_unit = result.get("unit")

    print(f"  route={route!r}, target_unit={target_unit!r}")
    print(f"  최종 답변: {answer!r}")

    print_raw_supabase_rows(price_data)
    check_normalization(price_data, judgments, target_unit)
    check_answer_matches_data(answer, judgments)


async def main() -> None:
    queries = sys.argv[1:] or _DEFAULT_QUERIES
    for query in queries:
        await run_check(query)
    print("=" * 70)
    print("모든 확인 완료")


if __name__ == "__main__":
    asyncio.run(main())
