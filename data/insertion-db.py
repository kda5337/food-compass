"""
KAMIS(농수산물) + 참가격(생필품) 품목명을 가져와서 하나의 Chroma DB 컬렉션에 저장하는 스크립트.

- KAMIS: productInfo(식량작물/채소류/특용작물/과일류/수산물) + dailySalesList(축산물)
- 참가격(price.go.kr): 생필품 품목 마스터
- "식품(가공식품)" 카테고리는 KAMIS/참가격 어디에도 없어서 별도 API(data.go.kr) 연동이 필요합니다.
"""

import os
import sys
import chromadb
import requests
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
from tqdm import tqdm
from collections import defaultdict

load_dotenv()  # .env 파일을 읽어 os.environ에 반영

KAMIS_CERT_KEY = os.getenv("KAMIS_CERT_KEY")
KAMIS_CERT_ID = os.getenv("KAMIS_CERT_ID")
PRICE_GOKR_SERVICE_KEY = os.getenv("PRICE_GOKR_SERVICE_KEY")

CHROMA_DB_PATH = "./data/chroma_db"
COLLECTION_NAME = "all_food_products"  # 모든 함수가 이 상수 하나만 참조


def check_env_vars() -> bool:
    """필요한 환경변수가 모두 채워져 있는지 먼저 확인."""
    missing = [
        name
        for name, value in [
            ("KAMIS_CERT_KEY", KAMIS_CERT_KEY),
            ("KAMIS_CERT_ID", KAMIS_CERT_ID),
            ("PRICE_GOKR_SERVICE_KEY", PRICE_GOKR_SERVICE_KEY),
        ]
        if not value
    ]
    if missing:
        print("[환경변수 누락] .env에 다음 값이 비어 있습니다:", ", ".join(missing))
        print("   .env.example을 복사해 .env로 만들고 실제 키 값을 채워주세요.\n")
        return False
    return True


# ── 1. KAMIS (농수산물 + 축산물) ────────────────────────────────────────

def get_kamis_names() -> list[str]:
    """KAMIS productInfo(5개 부류) + dailySalesList(축산물)을 합쳐서 전체 품목명 반환."""
    url = "https://www.kamis.or.kr/service/price/xml.do"
    print("── KAMIS (농수산물 품목 리스트) ──")

    # 1-1. productInfo — 식량작물/채소류/특용작물/과일류/수산물
    params_product_info = {
        "action": "productInfo",
        "p_cert_key": KAMIS_CERT_KEY,
        "p_cert_id": KAMIS_CERT_ID,
        "p_returntype": "json",
    }
    res = requests.get(url, params=params_product_info, timeout=10)
    data = res.json()

    error_code = data.get("error_code")
    items = data.get("info", [])

    base_names = []
    if error_code != "000":
        print(f"productInfo 실패 — error_code={error_code}")
        print(res.text[:300])
    else:
        by_category = defaultdict(set)
        for item in items:
            name = item.get("itemname")
            cat = item.get("itemcategoryname")
            if name and cat:
                by_category[cat].add(name)

        for cat, names in by_category.items():
            print(f"[{cat}] {len(names)}개: {sorted(names)}")

        base_names = list(dict.fromkeys(
            item.get("itemname") for item in items if item.get("itemname")
        ))

    # 1-2. dailySalesList — 축산물만 추출 (productInfo에는 축산물이 없음)
    params_daily_sales = {
        "action": "dailySalesList",
        "p_cert_key": KAMIS_CERT_KEY,
        "p_cert_id": KAMIS_CERT_ID,
        "p_returntype": "json",
    }
    res = requests.get(url, params=params_daily_sales, timeout=10)
    data = res.json()
    items = data.get("price", data.get("data", []))

    livestock_names = set()
    for item in items:
        if item.get("category_name") != "축산물":
            continue
        raw_name = item.get("item_name", "")
        name = raw_name.split("/")[0].strip()  # "돼지고기/kg" → "돼지고기"
        if name:
            livestock_names.add(name)

    livestock_names = sorted(livestock_names)
    print(f"[축산물] {len(livestock_names)}개: {livestock_names}")

    # 1-3. 합치기
    all_names = list(dict.fromkeys(base_names + livestock_names))
    print(f"\nKAMIS 총 {len(all_names)}개 (식품 제외 6개 부류)")

    return all_names


# ── 2. 참가격 (생필품) ───────────────────────────────────────────────

def get_price_gokr_items() -> list[dict]:
    """참가격 API에서 goodId + goodName을 함께 반환."""
    url = "http://openapi.price.go.kr/openApiImpl/ProductPriceInfoService/getProductInfoSvc.do"
    params = {"ServiceKey": PRICE_GOKR_SERVICE_KEY}

    print("── 참가격 (생필품 가격 정보) ──")
    res = requests.get(url, params=params, timeout=10)
    root = ET.fromstring(res.content)
    items = root.findall(".//item")

    results = []
    for item in items:
        gid = item.find("goodId")
        gname = item.find("goodName")
        if gid is not None and gname is not None and gname.text:
            results.append({"id": gid.text.strip(), "name": gname.text.strip()})

    print(f"참가격 총 {len(results)}개 품목")
    return results


# ── 3. 공통 유틸 ────────────────────────────────────────────────────

def names_to_items(names: list[str], prefix: str) -> list[dict]:
    """list[str] → [{'id': ..., 'name': ...}] 변환. id에 출처 prefix를 붙여 충돌 방지."""
    return [{"id": f"{prefix}_{i}", "name": name} for i, name in enumerate(names)]


def save_items_to_chroma(
    items: list[dict],
    collection_name: str = COLLECTION_NAME,
    batch_size: int = 50,
    path: str = CHROMA_DB_PATH,
):
    """items([{'id', 'name'}, ...])를 Chroma DB 컬렉션에 배치 저장."""
    client = chromadb.PersistentClient(path=path)
    collection = client.get_or_create_collection(name=collection_name)

    names = [it["name"] for it in items]
    ids = [it["id"] for it in items]

    for i in tqdm(range(0, len(items), batch_size), desc=f"'{collection_name}' 저장 중"):
        collection.add(
            documents=names[i:i + batch_size],
            ids=ids[i:i + batch_size],
        )

    print(f"Chroma DB '{collection_name}'에 누적 {collection.count()}개 품목 저장 완료")
    return collection


def delete_all_collections(path: str = CHROMA_DB_PATH):
    """Chroma DB의 모든 컬렉션을 삭제 (초기화용)."""
    client = chromadb.PersistentClient(path=path)
    collections = client.list_collections()

    if not collections:
        print("삭제할 컬렉션이 없습니다.")
        return

    print(f"총 {len(collections)}개 컬렉션 삭제 시작...")
    for col in collections:
        name = col.name if hasattr(col, "name") else col
        client.delete_collection(name=name)
        print(f"  - '{name}' 삭제 완료")
    print("모든 컬렉션 삭제 완료.")


def test_similar_search(
    query: str = "양배추",
    n_results: int = 3,
    path: str = CHROMA_DB_PATH,
    collection_name: str = COLLECTION_NAME,
):
    """저장된 컬렉션에서 query와 비슷한 단어 n개 찾기."""
    client = chromadb.PersistentClient(path=path)
    collection = client.get_collection(collection_name)

    results = collection.query(query_texts=[query], n_results=n_results)

    print(f"── '{query}'와 비슷한 품목 {n_results}개 (collection: {collection_name}) ──")
    for name, distance, id_ in zip(
        results["documents"][0],
        results["distances"][0],
        results["ids"][0],
    ):
        print(f"  {name}  (id={id_}, distance={distance:.4f})")

    return results


# ── 4. 실행 ─────────────────────────────────────────────────────────

def main():
    if not check_env_vars():
        sys.exit(1)

    delete_all_collections()

    print("\n── 결과 요약 ──")

    kamis_names = get_kamis_names()
    kamis_items = names_to_items(kamis_names, prefix="kamis")
    save_items_to_chroma(kamis_items, collection_name=COLLECTION_NAME)

    price_items = get_price_gokr_items()
    price_items = [{"id": f"pricegokr_{it['id']}", "name": it["name"]} for it in price_items]
    collection = save_items_to_chroma(price_items, collection_name=COLLECTION_NAME)

    print(f"\n최종 컬렉션 '{COLLECTION_NAME}' 총 {collection.count()}개 품목")


if __name__ == "__main__":
    main()
    test_similar_search("양배추")