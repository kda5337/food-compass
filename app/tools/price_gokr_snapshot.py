"""Supabase(PostgreSQL) price_gokr_* 테이블 저장/조회.

price_gokr_items/price_gokr_stores는 거의 안 바뀌는 마스터 데이터라 UPSERT만 하고
삭제하지 않음. price_gokr_snapshot만 시계열 데이터라 보관 기간(retention) 정리 대상.
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from app.tools.region import classify_region

load_dotenv()

_DATABASE_URL = os.getenv("DATABASE_URL", "")


# [2026-07-14 추가] 457개 품목을 순회하며 매번 새 연결을 여는 fetch 스크립트 실행 중
# "Temporary failure in name resolution"(DNS 일시 장애)로 전체가 중단되는 걸 실제로 겪음 —
# 이런 순간적인 네트워크 blip에 스크립트 전체가 죽지 않도록 연결 시도만 재시도
@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(psycopg2.OperationalError),
)
def _get_conn():
    url = urllib.parse.urlparse(_DATABASE_URL)
    return psycopg2.connect(
        host=url.hostname,
        port=url.port or 5432,
        dbname=url.path.lstrip("/"),
        user=urllib.parse.unquote(url.username or ""),
        password=urllib.parse.unquote(url.password or ""),
        sslmode="require",
    )


def save_items(items: list[dict[str, Any]]) -> int:
    """품목 마스터를 price_gokr_items에 UPSERT. 저장된 row 수 반환."""
    if not items:
        return 0

    rows = [
        (
            item["good_id"],
            item["good_name"],
            item.get("product_entp_code"),
            item.get("good_unit_div_code"),
            item.get("good_base_cnt"),
            item["good_smlcls_code"],
            item.get("good_total_cnt"),
            item.get("good_total_div_code"),
            item.get("detail_mean"),
        )
        for item in items
    ]

    conn = _get_conn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO price_gokr_items (
                good_id, good_name, product_entp_code, good_unit_div_code,
                good_base_cnt, good_smlcls_code, good_total_cnt,
                good_total_div_code, detail_mean
            )
            VALUES %s
            ON CONFLICT (good_id) DO UPDATE
                SET good_name = EXCLUDED.good_name,
                    product_entp_code = EXCLUDED.product_entp_code,
                    good_unit_div_code = EXCLUDED.good_unit_div_code,
                    good_base_cnt = EXCLUDED.good_base_cnt,
                    good_smlcls_code = EXCLUDED.good_smlcls_code,
                    good_total_cnt = EXCLUDED.good_total_cnt,
                    good_total_div_code = EXCLUDED.good_total_div_code,
                    detail_mean = EXCLUDED.detail_mean,
                    fetched_at = NOW();
            """,
            rows,
        )
        conn.commit()
        # [2026-07-14 확인] execute_values는 내부적으로 page_size(기본 100) 단위로 나눠 실행하는데
        # cur.rowcount는 마지막 페이지의 rowcount만 반환함(psycopg2 알려진 함정) — ON CONFLICT DO
        # UPDATE라 모든 입력 row가 반드시 insert/update 되므로 len(items)가 정확한 값
        cur.close()
    finally:
        conn.close()
    return len(items)


def save_stores(stores: list[dict[str, Any]]) -> int:
    """판매처 마스터를 price_gokr_stores에 UPSERT. 저장된 row 수 반환."""
    if not stores:
        return 0

    rows = [
        (
            store["entp_id"],
            store["entp_name"],
            store.get("entp_type_code"),
            store.get("entp_area_code"),
            store.get("area_detail_code"),
            store.get("entp_telno"),
            store.get("post_no"),
            store.get("plmk_addr_basic"),
            store.get("plmk_addr_detail"),
            store.get("road_addr_basic"),
            store.get("road_addr_detail"),
            store.get("x_map_coord"),
            store.get("y_map_coord"),
        )
        for store in stores
    ]

    conn = _get_conn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO price_gokr_stores (
                entp_id, entp_name, entp_type_code, entp_area_code,
                area_detail_code, entp_telno, post_no,
                plmk_addr_basic, plmk_addr_detail,
                road_addr_basic, road_addr_detail,
                x_map_coord, y_map_coord
            )
            VALUES %s
            ON CONFLICT (entp_id) DO UPDATE
                SET entp_name = EXCLUDED.entp_name,
                    entp_type_code = EXCLUDED.entp_type_code,
                    entp_area_code = EXCLUDED.entp_area_code,
                    area_detail_code = EXCLUDED.area_detail_code,
                    entp_telno = EXCLUDED.entp_telno,
                    post_no = EXCLUDED.post_no,
                    plmk_addr_basic = EXCLUDED.plmk_addr_basic,
                    plmk_addr_detail = EXCLUDED.plmk_addr_detail,
                    road_addr_basic = EXCLUDED.road_addr_basic,
                    road_addr_detail = EXCLUDED.road_addr_detail,
                    x_map_coord = EXCLUDED.x_map_coord,
                    y_map_coord = EXCLUDED.y_map_coord,
                    fetched_at = NOW();
            """,
            rows,
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return len(stores)


def save_store_regions() -> dict[str, int]:
    """price_gokr_stores의 주소를 8개 권역으로 분류해 price_gokr_store_regions에 UPSERT.

    분류 기준은 app/tools/region.py의 classify_region() 참고. 분류 불가한 매장(알려지지
    않은 주소 첫 토큰)은 저장하지 않고 개수만 세서 반환 — 임의로 추정해서 저장하지 않음.
    반환값: {"classified": 분류돼서 저장된 매장 수, "unclassified": 분류 실패 매장 수}
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT entp_id, plmk_addr_basic, road_addr_basic FROM price_gokr_stores;")
        stores = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    rows = []
    unclassified_ids = []
    for entp_id, plmk_addr, road_addr in stores:
        region = classify_region(plmk_addr) or classify_region(road_addr)
        if region is None:
            unclassified_ids.append(entp_id)
            continue
        rows.append((entp_id, region))

    if unclassified_ids:
        print(f"[save_store_regions] 지역 분류 실패 매장 {len(unclassified_ids)}개: {unclassified_ids}")

    if rows:
        conn = _get_conn()
        try:
            cur = conn.cursor()
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO price_gokr_store_regions (entp_id, region)
                VALUES %s
                ON CONFLICT (entp_id) DO UPDATE
                    SET region = EXCLUDED.region,
                        classified_at = NOW();
                """,
                rows,
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()

    return {"classified": len(rows), "unclassified": len(unclassified_ids)}


def save_price_snapshot(rows: list[dict[str, Any]]) -> int:
    """가격 관측치를 price_gokr_snapshot에 UPSERT. 저장된 row 수 반환."""
    if not rows:
        return 0

    values = [
        (
            row["good_inspect_day"],
            row["entp_id"],
            row["good_id"],
            int(row["good_price"]),
            row.get("good_dc_yn"),
            row.get("input_dttm"),
        )
        for row in rows
    ]

    conn = _get_conn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO price_gokr_snapshot (
                good_inspect_day, entp_id, good_id, good_price, good_dc_yn, input_dttm
            )
            VALUES %s
            ON CONFLICT (good_id, entp_id, good_inspect_day) DO UPDATE
                SET good_price = EXCLUDED.good_price,
                    good_dc_yn = EXCLUDED.good_dc_yn,
                    input_dttm = EXCLUDED.input_dttm,
                    fetched_at = NOW();
            """,
            values,
            template="(TO_DATE(%s, 'YYYYMMDD'), %s, %s, %s, %s, %s)",
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return len(rows)


def get_latest_prices(good_name: str) -> list[dict[str, Any]]:
    """품목명으로 가장 최근 조사일의 매장별 가격 전체 조회."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT i.good_name, s.entp_name, sn.good_price, sn.good_dc_yn,
                   sn.good_inspect_day, sn.input_dttm
            FROM price_gokr_snapshot sn
            JOIN price_gokr_items i ON i.good_id = sn.good_id
            JOIN price_gokr_stores s ON s.entp_id = sn.entp_id
            WHERE i.good_name = %s
              AND sn.good_inspect_day = (
                  SELECT MAX(sn2.good_inspect_day)
                  FROM price_gokr_snapshot sn2
                  JOIN price_gokr_items i2 ON i2.good_id = sn2.good_id
                  WHERE i2.good_name = %s
              );
            """,
            (good_name, good_name),
        )
        columns = [desc[0] for desc in cur.description]
        result_rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [dict(zip(columns, row, strict=True)) for row in result_rows]


def get_processed_price(good_name: str) -> dict[str, Any] | None:
    """가공식품(참가격) 품목명 기준 최신 조사일의 매장 평균가 조회.

    [시나리오 1: 쌀 vs 즉석밥] KAMIS와 달리 참가격은 매장별 개별가만 있고 전국
    대표가(평균/중간값) 개념이 없음 — 매장 편차를 직접 확인한 결과(햇반(210g) 기준
    443개 매장, 1,500~2,490원, 평균 1,946원/중앙값 1,880원) 극단적으로 치우친
    분포는 아니어서 단순 평균을 대표값으로 채택. good_name은 price_gokr_items의
    실제 상품명과 정확히 일치해야 함(일반 명칭 매핑은 app/tools/item_alias.py 담당).
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ROUND(AVG(sn.good_price), 1), COUNT(*), MAX(sn.good_inspect_day)
            FROM price_gokr_snapshot sn
            JOIN price_gokr_items i ON i.good_id = sn.good_id
            WHERE i.good_name = %s
              AND sn.good_inspect_day = (
                  SELECT MAX(sn2.good_inspect_day)
                  FROM price_gokr_snapshot sn2
                  JOIN price_gokr_items i2 ON i2.good_id = sn2.good_id
                  WHERE i2.good_name = %s
              );
            """,
            (good_name, good_name),
        )
        avg_price, sample_count, inspect_day = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if avg_price is None:
        return None
    return {
        "good_name": good_name,
        "avg_price": float(avg_price),
        "sample_count": sample_count,
        "inspect_day": inspect_day.isoformat() if inspect_day else None,
    }


def delete_old_snapshots(retention_days: int = 30) -> int:
    """good_inspect_day가 (오늘 - retention_days)보다 오래되고, 테이블에 남아있는
    가장 최신 good_inspect_day보다도 오래된 row만 삭제. 삭제 건수 반환.

    [2026-07-14 버그 수정] 처음엔 "오늘 - retention_days"만 기준으로 지웠는데, 실제로
    돌려보니 조사 주기가 격주보다도 더 불규칙하게 밀려서(2026-06-26 이후 다음 조사가
    2주 뒤인 7/10에도 안 올라옴) retention_days=15로는 방금 막 받은 유일한 데이터까지
    스크립트가 끝나자마자 자기 손으로 지워버리는 사고가 났음(457개 품목, 99,859건 전체
    삭제 — 재현 확인함). 다음 조사가 언제 올라올지 예측 불가능한 소스라 "N일 지나면
    무조건 삭제"는 근본적으로 안전하지 않음 — 그래서 "테이블에 남은 가장 최신
    good_inspect_day는 아무리 오래돼도 절대 지우지 않는다"는 안전장치를 추가하고,
    retention_days도 여유 있게 30일로 늘림. price_gokr_items/stores(마스터)는
    이 정리 대상이 아님.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM price_gokr_snapshot
            WHERE good_inspect_day < CURRENT_DATE - (%s * INTERVAL '1 day')
              AND good_inspect_day < (SELECT MAX(good_inspect_day) FROM price_gokr_snapshot);
            """,
            (retention_days,),
        )
        conn.commit()
        deleted = cur.rowcount
        cur.close()
    finally:
        conn.close()
    return deleted
