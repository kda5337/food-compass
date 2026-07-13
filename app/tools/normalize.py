"""가격 단위 환산 — CLAUDE.md §16.2의 `normalize_unit` 툴에 대응하는 파일.

app/tools/judge.py의 judge_price()가 판정 전에 쓰는 일반 무게/개수 단위 환산과,
시나리오 1(쌀 vs 즉석밥)에서만 쓰는 "밥 1공기" 환산을 모두 이 파일에서 관리한다.
원래 normalize_price_unit()이 judge.py에 있었는데, "단위 환산 -> 가격 판정"
순서(§6.2)와 반대로 judge.py가 정의하고 normalize.py가 그걸 가져다 쓰는 역방향
의존이 되어 있었음 — 여기로 옮기고 judge.py가 이 파일을 import하도록 정리.
"""
from __future__ import annotations

import re

# 무게 단위 -> 그램 환산 계수
_WEIGHT_UNIT_TO_GRAM = {"kg": 1000, "g": 1}

# 개수 기반 단위 (1개당으로 환산할 대상)
_COUNT_UNITS = {"개", "속", "단", "포기", "마리", "봉", "팩", "모"}

# [설계 논의로 확정, 2026-07-14] 국립농산물품질관리원 등에서 흔히 쓰는 환산 기준:
# 마른 쌀 90g을 지으면 지어진 밥 210g(1공기)이 나옴 — 참가격 DB의 대표 상품으로 고른
# "즉석밥(햇반 210g)"과 정확히 같은 결과물(밥 1공기) 기준이라 이 값을 그대로 재사용.
# 이 환산 기준은 반드시 답변에도 그대로 공시한다(사용자 요청, app/prompts/prompts.py
# COMPARISON_ANSWER_SYSTEM_PROMPT 참고).
DRY_RICE_GRAMS_PER_BOWL = 90


# [2026-07-14 이동] 원래 app/tools/judge.py에 정의돼 있던 함수(및 위 두 상수)를
# 이 파일로 옮김 — 옮기기 전까지는 이 파일(normalize.py)이 오히려 judge.py의
# normalize_price_unit을 import해서 쓰는 역방향 의존 구조였음. "단위 환산이 먼저,
# 가격 판정이 그 다음"이라는 파이프라인 순서(CLAUDE.md §6.2)에 맞춰 이 파일이
# normalize_unit 툴의 실제 구현 위치가 되도록 정리했고, judge.py는 이제
# `from app.tools.normalize import normalize_price_unit`로 가져다 쓰기만 함.
# 로직 자체는 이동 전과 완전히 동일 — 순수 코드 위치 이동(변수/동작 변경 없음).
def normalize_price_unit(
    price: float | None, unit: str | None
) -> tuple[float | None, str | None]:
    """가격을 표준 단위로 환산.

    - 무게 단위(kg, g)는 100g당 가격으로 변환.
    - 개수 단위(개, 속, 단 등)는 1개당 가격으로 변환.
    - unit이 없거나("" / None), 형식을 인식할 수 없으면 변환하지 않고 원본 그대로 반환.

    예시:
        normalize_price_unit(3000, "1kg")   -> (300.0, "100g")
        normalize_price_unit(3000, "20kg")  -> (15.0, "100g")
        normalize_price_unit(500, "100g")   -> (500.0, "100g")  # 이미 100g 기준
        normalize_price_unit(5000, "10개")  -> (500.0, "1개")
        normalize_price_unit(3000, "1개")   -> (3000.0, "1개")
        normalize_price_unit(3000, "")      -> (3000, "")        # 스킵
        normalize_price_unit(3000, "1속")   -> (3000.0, "1속")
    """
    if price is None or not unit:
        return price, unit

    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z가-힣]+)\s*$", unit.strip())
    if not match:
        # "1kg" 같은 숫자+단위 형식이 아니면 인식 불가 — 변환 스킵
        return price, unit

    qty = float(match.group(1))
    unit_label = match.group(2)

    if unit_label in _WEIGHT_UNIT_TO_GRAM:
        total_grams = qty * _WEIGHT_UNIT_TO_GRAM[unit_label]
        if total_grams <= 0:
            return price, unit
        normalized_price = round(price / total_grams * 100, 1)
        return normalized_price, "100g"

    if unit_label in _COUNT_UNITS:
        if qty <= 0:
            return price, unit
        normalized_price = round(price / qty, 1)
        return normalized_price, f"1{unit_label}"

    # 알려지지 않은 단위(예: "1단(500g)" 같은 복합 표기)는 변환하지 않고 그대로 반환
    return price, unit


# [2026-07-14 신규, 시나리오 1: 쌀 vs 즉석밥] 위 normalize_price_unit()은 일반적인
# 무게/개수 단위 환산까지만 하고 멈추는데(예: 20kg -> 100g당 가격), 이 함수는 그
# 결과를 "밥 1공기" 기준으로 한 단계 더 환산함 — 원물(쌀)과 가공식품(즉석밥)의
# 가격을 서로 비교하려면 최종적으로 같은 결과물(밥 1공기) 기준으로 맞춰야 하기 때문.
# app/graph/nodes.py의 compare_items_node에서만 사용됨.
def rice_price_per_bowl(price: float, unit: str | None) -> float | None:
    """쌀 판매 단위 가격(예: 60,800원/20kg)을 '밥 1공기(마른 쌀 90g)' 기준 가격으로 환산.

    unit이 무게 단위(kg/g)로 인식되지 않으면(예: 형식 불명) None을 반환 — 임의로
    추정하지 않음.
    """
    price_per_100g, normalized_unit = normalize_price_unit(price, unit)
    if price_per_100g is None or normalized_unit != "100g":
        return None
    return round(price_per_100g * DRY_RICE_GRAMS_PER_BOWL / 100, 1)
