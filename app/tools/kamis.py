from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.tools.judge import parse_price
from app.tools.price_snapshot import get_latest_prices

if TYPE_CHECKING:
    from app.graph.state import AgentState

_DPR_FIELDS = ("dpr1", "dpr2", "dpr3", "dpr4", "dpr5", "dpr6", "dpr7")
_PREFERRED_RANK = "상품"  # 여러 등급(상품/중품 등) 중 대표로 삼을 등급

# [2026-07-14 확인] KAMIS 응답에 실제로 딸려오는 day1~day7 라벨로 확인한 dpr1~dpr7 의미:
#   dpr1=당일, dpr2=1일전, dpr3=1주일전, dpr4=2주일전, dpr5=1개월전, dpr6=1년전, dpr7=일평년(평년가)
# dpr7(평년가)은 judge_price의 비교 기준 그 자체라 fallback 후보에서 제외.
# dpr6(1년전)도 제외 — "오늘 가격 없으니 최근 데이터로 보완"이라는 취지에서 1년 전 가격까지
# 끌어와 "당일가"인 것처럼 쓰면 계절/물가 변동을 무시하고 왜곡된 판정을 낼 수 있어 너무 멂.
_FALLBACK_FIELDS = ("dpr2", "dpr3", "dpr4", "dpr5")

# [2026-07-14 추가] fallback으로 어떤 필드를 썼는지 답변에 "N일 전 기준"으로 밝히기 위한 라벨.
# dpr1 자체(당일)도 포함해서, fallback 없이 당일가를 그대로 쓴 경우와 구분할 수 있게 함.
_DAY_LABELS = {
    "dpr1": "당일",
    "dpr2": "1일전",
    "dpr3": "1주일전",
    "dpr4": "2주일전",
    "dpr5": "1개월전",
}


def _pick_representative_row(rows: list[dict]) -> dict:
    """같은 품목의 여러 품종·등급 row 중 대표 1건 선택 — '상품' 등급 우선, 없으면 첫 row."""
    for row in rows:
        if row.get("rank_name") == _PREFERRED_RANK:
            return row
    return rows[0]


def _resolve_today_price(row: dict) -> dict:
    """당일가(dpr1)가 '-'(당일 데이터 미반영)이면 dpr2→dpr5(1개월전까지) 순서로 값이 있는 첫 필드로 대체.

    [2026-07-14 수정] 기존엔 dpr2(전일가) 한 단계만 시도하고 그래도 없으면 그냥 포기했음.
    실제로 축산물(500)을 제외한 전 부류에서 dpr1·dpr2가 동시에 결측인 날이 있는데, 그런
    경우도 dpr3~dpr5엔 값이 남아있는 걸 확인함(§11 "가격 데이터 결측 시 과거 데이터로
    보완" 원칙과도 일치) — 1개월전(dpr5)까지 순서대로 폴백하도록 확장. dpr6(1년전)은
    너무 멀어서 fallback 후보에서 제외(위 _FALLBACK_FIELDS 주석 참고).

    [2026-07-14 추가] fallback으로 며칠 전 값을 끌어왔는지 사용자에게 "N일 전 기준"으로
    투명하게 밝히기 위해, 실제 사용된 필드가 며칠 전인지를 resolved["price_as_of"]에
    담아 반환 — 당일가를 그대로 썼으면 "당일", fallback을 탔으면 그 필드의 라벨, 아무
    필드도 못 찾았으면 None(가격 데이터 자체가 없는 경우이므로 시점 표기 불필요).
    """
    resolved = dict(row)
    resolved["price_as_of"] = _DAY_LABELS["dpr1"]
    if parse_price(resolved.get("dpr1", "-")) is None:
        resolved["price_as_of"] = None
        for field in _FALLBACK_FIELDS:
            fallback = resolved.get(field, "-")
            if parse_price(fallback) is not None:
                resolved["dpr1"] = fallback
                resolved["price_as_of"] = _DAY_LABELS[field]
                break
    return resolved


def get_raw_price_node(state: AgentState) -> dict[str, Any]:
    """Supabase price_snapshot에서 실제 KAMIS 시세(당일·1주일전·1개월전·평년)를 조회.

    - DB에 없는 품목은 found=False로 표시 — 값을 임의로 채우지 않음(§11-3, 미지원 품목 안내).
    - DB 조회 자체가 실패하면(연결 오류 등) 동일하게 미지원으로 처리.
    """
    items = state.get("items", [])
    price_data = []
    for item_name in items:
        try:
            rows = get_latest_prices(item_name)
        except Exception as e:
            print(f"[get_raw_price] DB 조회 실패: {e}")
            rows = []

        if not rows:
            price_data.append(
                {
                    "item_name": item_name,
                    "unit": "-",
                    "found": False,
                    **{field: "-" for field in _DPR_FIELDS},
                }
            )
            continue

        row = _resolve_today_price(_pick_representative_row(rows))
        price_data.append(
            {
                "item_name": row["item_name"],
                "unit": row["unit"],
                "found": True,
                "price_as_of": row.get("price_as_of"),
                **{field: row.get(field, "-") for field in _DPR_FIELDS},
            }
        )
    return {"price_data": price_data}
