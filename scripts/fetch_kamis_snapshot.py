"""KAMIS 전체 부류 가격 조회 → Supabase price_snapshot 적재.

1회성 테스트 및 향후 GitHub Actions cron의 기반이 되는 스크립트.

실행:
    $env:PYTHONUTF8=1
    .venv/Scripts/python.exe scripts/fetch_kamis_snapshot.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.kamis_client import CATEGORY_CODES, fetch_category_prices
from app.tools.price_snapshot import delete_old_snapshots, save_price_snapshot

# [2026-07-14 추가] price_snapshot이 매일 무한정 쌓이는 걸 막기 위한 보관 기간(일)
_RETENTION_DAYS = 7


def main() -> None:
    regday = date.today().isoformat()
    print(f"조회 기준일: {regday}")
    print("=" * 50)

    total_saved = 0
    for category_code, label in CATEGORY_CODES.items():
        items = fetch_category_prices(category_code, regday=regday)
        saved = save_price_snapshot(items, regday=regday)
        total_saved += saved
        print(f"[{category_code}] {label}: {len(items)}건 조회 -> {saved}건 저장")

    print("=" * 50)
    print(f"전체 저장 완료: {total_saved}건")

    # 오늘자 저장이 다 끝난 뒤에 지우기 — 저장 도중 실패해도 기존 데이터가 먼저 날아가지 않도록
    deleted = delete_old_snapshots(retention_days=_RETENTION_DAYS)
    print(f"{_RETENTION_DAYS}일 이전 스냅샷 정리: {deleted}건 삭제")


if __name__ == "__main__":
    main()
