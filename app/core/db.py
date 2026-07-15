"""Supabase(PostgreSQL) 연결 공용 헬퍼.

[2026-07-15 리팩터링] 완전히 동일한 `_get_conn()` 구현이 price_cache.py /
price_snapshot.py / price_gokr_snapshot.py 세 파일에 복제돼 있던 것을 한 곳으로 통합.
연결 문자열 파싱·sslmode·재시도 정책이 한 파일에서만 관리되도록 함.

재시도: fetch 스크립트가 수백 개 품목을 순회하며 매번 새 연결을 열다 "Temporary
failure in name resolution"(DNS 일시 장애)로 전체가 중단되는 걸 실제로 겪어서(2026-07-14),
연결 시도에 한해 3회/2초 간격 재시도를 붙임 — 기존에 재시도가 없던 price_cache(ping 등)도
이 통합으로 동일한 회복력을 얻음.
"""
from __future__ import annotations

import os
import urllib.parse

import psycopg2
from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

load_dotenv()

_DATABASE_URL = os.getenv("DATABASE_URL", "")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(psycopg2.OperationalError),
)
def get_conn():
    """DATABASE_URL 기반 psycopg2 연결 생성 — OperationalError 시 3회까지 재시도."""
    url = urllib.parse.urlparse(_DATABASE_URL)
    return psycopg2.connect(
        host=url.hostname,
        port=url.port or 5432,
        dbname=url.path.lstrip("/"),
        user=urllib.parse.unquote(url.username or ""),
        password=urllib.parse.unquote(url.password or ""),
        sslmode="require",
    )
