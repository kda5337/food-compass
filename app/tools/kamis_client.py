"""KAMIS dailyPriceByCategoryList 실 API 클라이언트.

- 부류코드(item_category_code) 단위로 요청 → 해당 부류의 전체 품목/품종/등급 row를 한 번에 받음
  (개별 품목 코드 매핑 불필요)
- KAMIS 서버가 legacy TLS 설정이라 기본 SSL 컨텍스트로는 handshake 실패 → 완화된 컨텍스트 사용
"""
from __future__ import annotations

import os
import ssl
from datetime import date
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

_KAMIS_URL = "https://www.kamis.or.kr/service/price/xml.do"

# 부류코드 (KAMIS 실 응답으로 검증 완료)
CATEGORY_CODES: dict[str, str] = {
    "100": "식량작물",
    "200": "채소류",
    "300": "특용작물",
    "400": "과일류",
    "500": "축산물",
    "600": "수산물",
}


def _legacy_ssl_context() -> ssl.SSLContext:
    """KAMIS 서버의 오래된 TLS 설정과 handshake 하기 위한 완화된 컨텍스트."""
    ctx = ssl.create_default_context()
    ctx.options |= 0x4  # ssl.OP_LEGACY_SERVER_CONNECT
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    return ctx


def fetch_category_prices(
    category_code: str,
    regday: str | None = None,
    product_cls_code: str = "02",
) -> list[dict[str, Any]]:
    """부류코드 하나에 대한 전체 품목/품종/등급 가격 row를 반환.

    product_cls_code: "01"=도매, "02"=소매
    regday: "YYYY-MM-DD" (미지정 시 오늘)
    """
    cert_key = os.environ["KAMIS_CERT_KEY"]
    cert_id = os.environ["KAMIS_CERT_ID"]

    params = {
        "action": "dailyPriceByCategoryList",
        "p_product_cls_code": product_cls_code,
        "p_item_category_code": category_code,
        "p_regday": regday or date.today().isoformat(),
        "p_convert_kg_yn": "N",
        "p_cert_key": cert_key,
        "p_cert_id": cert_id,
        "p_returntype": "json",
    }

    response = httpx.get(_KAMIS_URL, params=params, timeout=15, verify=_legacy_ssl_context())
    response.raise_for_status()
    data = response.json()

    items = data.get("data", {}).get("item", [])
    if not isinstance(items, list):
        # KAMIS는 결과가 없거나 에러일 때 item을 dict/문자열로 반환하기도 함
        return []

    # KAMIS 응답 자체에는 부류코드가 없으므로(요청 파라미터로만 구분) 직접 주입
    for item in items:
        item["item_category_code"] = category_code
    return items


def fetch_all_categories(regday: str | None = None) -> list[dict[str, Any]]:
    """전체 부류(6종)를 순회하며 가격 row를 모두 수집."""
    all_items: list[dict[str, Any]] = []
    for category_code in CATEGORY_CODES:
        all_items.extend(fetch_category_prices(category_code, regday=regday))
    return all_items
