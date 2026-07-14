"""대체품 유사도 검색용 ChromaDB 컬렉션(all_food_products)을 재구축하는 스크립트.

[2026-07-15 신설] 기존 insertion-chroma-db.py는 (1) KAMIS + data.go.kr(식료품)을 모두
적재하고 (2) KAMIS 이름을 API에서 가져와 "돼지고기"처럼 판정 결과 이름("돼지")과
어긋나게 저장하며 (3) 부류(category) 메타데이터가 없어 "소"의 대체품으로 천일염·새우젓
같은 다른 부류가 섞여 나오는 문제가 있었음.

이 스크립트는 그 세 가지를 한 번에 정리한다:
- data.go.kr(식료품) 문서는 넣지 않음 — 대체품은 KAMIS 원물에만 쓰이므로 불필요.
- Supabase price_snapshot의 DISTINCT item_name을 그대로 문서로 사용 → 판정 결과 이름과
  100% 일치(소/돼지/닭/풋고추 등). 실제로 가격을 조회할 수 있는 품목만 대체품 후보가 됨.
- 각 문서에 category(식량작물/채소류/특용작물/과일류/축산물/수산물) 메타데이터를 붙여,
  대체품 검색이 "같은 부류 안에서만" 유사도 검색하도록(app/graph/nodes.py) 한다.

실행(로컬): `.venv/bin/python data/build_substitute_collection.py`
실행(서버): `docker compose -f docker-compose.prod.yml exec api .venv/bin/python data/build_substitute_collection.py`
"""
from __future__ import annotations

import os
from pathlib import Path

import chromadb
import psycopg2
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

load_dotenv()

_HERE = Path(__file__).resolve().parent
CHROMA_DB_PATH = str(_HERE / "chroma_db")
COLLECTION_NAME = "all_food_products"

EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")
korean_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL_NAME
)

# KAMIS 부류코드 -> 부류명 (app/tools/kamis_client.py의 CATEGORY_CODES와 동일)
CATEGORY_CODES = {
    "100": "식량작물",
    "200": "채소류",
    "300": "특용작물",
    "400": "과일류",
    "500": "축산물",
    "600": "수산물",
}


def _fetch_kamis_items() -> list[tuple[str, str]]:
    """price_snapshot에서 (품목명, 부류명) 목록을 중복 없이 조회."""
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT item_name, item_category_code FROM price_snapshot ORDER BY item_name;"
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    items = []
    for item_name, code in rows:
        category = CATEGORY_CODES.get(code)
        if category is None:
            print(f"[경고] 매핑 안 되는 부류코드 {code!r} — 품목 '{item_name}' 건너뜀")
            continue
        items.append((item_name, category))
    return items


def main() -> None:
    items = _fetch_kamis_items()
    print(f"KAMIS 품목 {len(items)}개 로드 완료 (부류 메타데이터 포함)")

    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    # 기존 all_food_products(KAMIS + data.go.kr 혼재)를 지우고 KAMIS 전용으로 새로 만든다.
    # food_knowledge 등 다른 컬렉션은 건드리지 않음.
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"기존 '{COLLECTION_NAME}' 컬렉션 삭제(data.go.kr 문서 포함 전부 제거)")
    except Exception:
        pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=korean_embedding_fn,
    )
    collection.add(
        documents=[name for name, _ in items],
        ids=[f"kamis_{i}" for i in range(len(items))],
        metadatas=[{"name": name, "source": "kamis", "category": cat} for name, cat in items],
    )
    print(f"'{COLLECTION_NAME}'에 KAMIS 품목 {collection.count()}개 저장 완료(부류별 분류)")


if __name__ == "__main__":
    main()
