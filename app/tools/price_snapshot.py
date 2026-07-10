"""Supabase(PostgreSQL) price_snapshot 테이블 저장/조회.

KAMIS 응답을 가공 없이 그대로 적재 — 등급/품종별 row 전부 유지.
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

_DATABASE_URL = os.getenv("DATABASE_URL", "")

_DPR_FIELDS = ("dpr1", "dpr2", "dpr3", "dpr4", "dpr5", "dpr6", "dpr7")


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


def save_price_snapshot(items: list[dict[str, Any]], regday: str, source: str = "KAMIS") -> int:
    """KAMIS 응답 row 리스트를 price_snapshot에 UPSERT. 저장된 row 수 반환."""
    if not items:
        return 0

    rows = [
        (
            item["item_category_code"],
            item["item_name"],
            item["item_code"],
            item["kind_name"],
            item["kind_code"],
            item["rank"],
            item["rank_code"],
            item["unit"],
            *(item.get(field, "-") for field in _DPR_FIELDS),
            regday,
            source,
        )
        for item in items
    ]

    conn = _get_conn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO price_snapshot (
                item_category_code, item_name, item_code, kind_name, kind_code,
                rank_name, rank_code, unit,
                dpr1, dpr2, dpr3, dpr4, dpr5, dpr6, dpr7,
                regday, source
            )
            VALUES %s
            ON CONFLICT (item_code, kind_code, rank_code, regday) DO UPDATE
                SET dpr1 = EXCLUDED.dpr1,
                    dpr2 = EXCLUDED.dpr2,
                    dpr3 = EXCLUDED.dpr3,
                    dpr4 = EXCLUDED.dpr4,
                    dpr5 = EXCLUDED.dpr5,
                    dpr6 = EXCLUDED.dpr6,
                    dpr7 = EXCLUDED.dpr7,
                    fetched_at = NOW();
            """,
            rows,
        )
        conn.commit()
        saved = cur.rowcount
        cur.close()
    finally:
        conn.close()
    return saved


def get_latest_prices(item_name: str) -> list[dict[str, Any]]:
    """품목명으로 가장 최근 regday의 전체 row(등급/품종별)를 조회."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT item_name, item_code, kind_name, kind_code, rank_name, rank_code,
                   unit, dpr1, dpr2, dpr3, dpr4, dpr5, dpr6, dpr7, regday, source, fetched_at
            FROM price_snapshot
            WHERE item_name = %s
              AND regday = (
                  SELECT MAX(regday) FROM price_snapshot WHERE item_name = %s
              );
            """,
            (item_name, item_name),
        )
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [dict(zip(columns, row)) for row in rows]
