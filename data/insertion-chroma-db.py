"""
KAMIS(농수산물) + 참가격(생필품) 품목명을 가져와서 하나의 Chroma DB 컬렉션에 저장하는 스크립트.

- KAMIS: productInfo(식량작물/채소류/특용작물/과일류/수산물) + dailySalesList(축산물)
- 참가격(price.go.kr): 생필품 품목 마스터
- "식품(가공식품)" 카테고리는 KAMIS/참가격 어디에도 없어서 별도 API(data.go.kr) 연동이 필요합니다.
"""

import os
import sys
import gc
import shutil
import asyncio
import chromadb
import httpx
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm
from collections import defaultdict
from langchain_upstage import ChatUpstage
from langchain_core.messages import HumanMessage, SystemMessage
from chromadb.utils import embedding_functions

# [2026-07-13 수정] KAMIS 요청에 app/tools/kamis_client.py의 legacy SSL 컨텍스트를 재사용하기 위해
# 프로젝트 루트를 sys.path에 추가 (scripts/fetch_kamis_snapshot.py와 동일한 패턴)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.tools.kamis_client import _legacy_ssl_context  # noqa: E402

load_dotenv()  # .env 파일을 읽어 os.environ에 반영

KAMIS_CERT_KEY = os.getenv("KAMIS_CERT_KEY")
KAMIS_CERT_ID = os.getenv("KAMIS_CERT_ID")
PRICE_GOKR_SERVICE_KEY = os.getenv("PRICE_GOKR_SERVICE_KEY")
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "solar-pro")

CHROMA_DB_PATH = "./data/chroma_db"
COLLECTION_NAME = "all_food_products"  # 모든 함수가 이 상수 하나만 참조

# 한국어 문장 유사도(STS)에 특화된 임베딩 모델.
# 기본 Chroma 임베딩(all-MiniLM-L6-v2, 영어 위주)보다 한국어 단어/문장 비교에 훨씬 적합.
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")
korean_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL_NAME)

DESC_SYSTEM_PROMPT = (
    '''
    너는 농축수산물/생필품 품목의 검색용 설명을 만드는 도우미다.
    입력으로 품목명 하나가 주어지면, 반드시 "품목명: 설명" 형식으로 한 줄만 답하라.

    설명 부분에는 그 품목에 실제로 해당하는 것들을 자연스럽게 녹여 넣어라:
    부류(채소/과일/곡물/수산물/축산물 등), 맛(달다/맵다/짜다/고소하다/새콤하다 등),
    식감이나 색깔·생김새, 주로 쓰이는 요리나 용도.

    "~는 ~이다"처럼 품목명을 그대로 풀어쓰는 사전적 정의문은 피하고,
    사람이 실제로 검색할 때 쓸 법한 자연스러운 표현으로 설명 부분은 30자 내외로 작성하라.
    숫자, 브랜드명, 가격 정보는 포함하지 마라.
    "품목명: 설명" 형식 외에 다른 말은 절대 덧붙이지 마라.

    예시:
    고춧가루: 매콤한 붉은빛 양념, 김치나 찌개에 널리 쓰임
    갈치: 길고 은빛 도는 생선, 구이나 조림으로 즐겨 먹음
    딸기: 새콤달콤한 붉은 과일, 디저트나 간식으로 인기
    '''
)


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
    # [2026-07-13 수정] KAMIS 서버가 legacy TLS 설정이라 requests 기본 SSL 컨텍스트로는
    # handshake 단계에서 계속 renegotiation을 요구하다 타임아웃남(SSLError/응답 없음).
    # "KAMIS가 막혔다"고 보였던 원인이 이거였음 — 완전 차단이 아니라 완화된 SSL 컨텍스트 없이
    # 접속하는 모든 클라이언트(requests, curl, 브라우저 등)가 다 실패하는 것.
    # app/tools/kamis_client.py에서 이미 같은 문제를 httpx + _legacy_ssl_context()로 해결해둔 게
    # 있어서(그쪽은 실제로 지금도 정상 동작 확인함) 그대로 재사용함. timeout도 그쪽과 동일하게 15초로 맞춤.
    res = httpx.get(url, params=params_product_info, timeout=15, verify=_legacy_ssl_context())
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
    # [2026-07-13 수정] 바로 위 productInfo 호출과 같은 이유로 requests → httpx(legacy SSL) 전환
    res = httpx.get(url, params=params_daily_sales, timeout=15, verify=_legacy_ssl_context())
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
    """list[str] → [{'id': ..., 'document': ...}] 변환. id에 출처 prefix를 붙여 충돌 방지.
    document가 곧 임베딩되는 텍스트."""
    return [{"id": f"{prefix}_{i}", "document": name} for i, name in enumerate(names)]


def save_items_to_chroma(
    items: list[dict],
    collection_name: str = COLLECTION_NAME,
    batch_size: int = 50,
    path: str = CHROMA_DB_PATH,
):
    """items([{'id', 'document', 'metadata'(선택)}, ...])를 Chroma DB 컬렉션에 배치 저장.
    'document'에 넣은 텍스트가 곧 임베딩(벡터화)되는 대상입니다."""
    client = chromadb.PersistentClient(path=path)
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=korean_embedding_fn,
    )

    documents = [it["document"] for it in items]
    ids = [it["id"] for it in items]
    metadatas = [it.get("metadata") for it in items]
    has_metadata = any(m for m in metadatas)

    for i in tqdm(range(0, len(items), batch_size), desc=f"'{collection_name}' 저장 중"):
        batch_kwargs = {
            "documents": documents[i:i + batch_size],
            "ids": ids[i:i + batch_size],
        }
        if has_metadata:
            batch_kwargs["metadatas"] = metadatas[i:i + batch_size]
        collection.add(**batch_kwargs)

    print(f"Chroma DB '{collection_name}'에 누적 {collection.count()}개 품목 저장 완료")
    return collection


def delete_all_collections(path: str = CHROMA_DB_PATH, remove_files: bool = True):
    """Chroma DB의 모든 컬렉션을 삭제 (초기화용).

    remove_files=True(기본값)면 API로 컬렉션을 지운 뒤, chroma_db 폴더 자체를
    통째로 삭제해서 orphan(고아) UUID 폴더까지 완전히 제거합니다.
    """
    client = chromadb.PersistentClient(path=path)
    collections = client.list_collections()

    if collections:
        print(f"총 {len(collections)}개 컬렉션 삭제 시작...")
        for col in collections:
            name = col.name if hasattr(col, "name") else col
            client.delete_collection(name=name)
            print(f"  - '{name}' 삭제 완료")
    else:
        print("삭제할 컬렉션이 없습니다.")

    if not remove_files:
        print("모든 컬렉션 삭제 완료.")
        return

    # Windows에서는 sqlite 파일 핸들이 남아있으면 폴더 삭제가 막힐 수 있어서
    # client 참조를 먼저 놓아준다.
    del client
    gc.collect()

    if not os.path.exists(path):
        print(f"'{path}' 폴더가 이미 없습니다.")
        return

    try:
        shutil.rmtree(path)
        print(f"'{path}' 폴더 자체를 완전히 삭제했습니다 (orphan 폴더 포함).")
    except PermissionError as e:
        print(f"[삭제 실패] 폴더가 다른 프로세스에 의해 사용 중입니다: {e}")
        print("   VS Code 등에서 chroma_db 관련 파일/탭을 닫고 다시 시도해보세요.")


def test_similar_search(
    query: str,
    n_results: int = 3,
    path: str = CHROMA_DB_PATH,
    collection_name: str = COLLECTION_NAME,
):
    """저장된 컬렉션에서 query와 비슷한 텍스트 n개 찾기 (검색어 자기 자신은 제외).
    KAMIS 품목은 documents가 '설명'이라, metadata의 원래 이름도 같이 보여줍니다."""
    client = chromadb.PersistentClient(path=path)
    collection = client.get_collection(
        collection_name,
        embedding_function=korean_embedding_fn,
    )

    # 자기 자신이 걸러질 걸 대비해 필요한 개수보다 여유 있게 가져온다
    results = collection.query(
        query_texts=[query],
        n_results=n_results + 5,
        where={"source": "kamis"},
        include=["documents", "distances", "metadatas"],
    )

    print(f"── '{query}'와 비슷한 항목 {n_results}개 (collection: {collection_name}) ──")

    shown = 0
    for document, distance, id_, meta in zip(
        results["documents"][0],
        results["distances"][0],
        results["ids"][0],
        results["metadatas"][0],
    ):
        original_name = (meta or {}).get("name")

        # 검색어 자기 자신(설명이든 원래 이름이든)과 완전히 일치하면 제외
        if document == query or original_name == query:
            continue

        if original_name and original_name != document:
            print(f"  {original_name}  (id={id_}, distance={distance:.4f}) — {document}")
        else:
            print(f"  {document}  (id={id_}, distance={distance:.4f})")

        shown += 1
        if shown >= n_results:
            break

    if shown == 0:
        print("  (자기 자신을 제외하고 나니 결과가 없습니다.)")

    return results

# ── 4. KAMIS 품목 설명 생성 (설명 자체를 임베딩 대상으로 사용) ──────────
#     get_kamis_names()로 얻은 품목명마다 한줄 설명을 만들고,
#     그 "설명 텍스트"를 documents(임베딩 대상)로 저장합니다.
#     원래 품목명은 metadata["name"]에 남겨서 나중에 표시용으로 씁니다.

def _get_desc_llm() -> ChatUpstage:
    return ChatUpstage(
        api_key=UPSTAGE_API_KEY,
        model=LLM_MODEL,
        timeout=30,
        max_retries=2,
    )


async def _generate_one_description(llm, semaphore: asyncio.Semaphore, name: str) -> tuple[str, str]:
    async with semaphore:
        try:
            messages = [
                SystemMessage(content=DESC_SYSTEM_PROMPT),
                HumanMessage(content=name),
            ]
            result = await llm.ainvoke(messages)
            desc = result.content.strip()
        except Exception as e:
            print(f"[설명 생성 실패] {name}: {e}")
            desc = ""
        return name, desc


async def _generate_descriptions_with_progress(
    names: list[str], concurrency: int = 5
) -> dict[str, str]:
    """이름 목록 → {이름: 한줄설명} 매핑. 진행률을 tqdm으로 실시간 표시."""
    llm = _get_desc_llm()
    semaphore = asyncio.Semaphore(concurrency)

    tasks = [
        asyncio.ensure_future(_generate_one_description(llm, semaphore, name))
        for name in names
    ]

    descriptions: dict[str, str] = {}
    with tqdm(total=len(tasks), desc="설명 생성 중") as pbar:
        for coro in asyncio.as_completed(tasks):
            name, desc = await coro
            descriptions[name] = desc
            pbar.update(1)
            pbar.set_postfix_str(name[:10])  # 방금 처리한 품목명 우측에 표시

    return descriptions


def get_kamis_items_with_descriptions(concurrency: int = 5) -> list[dict]:
    """KAMIS 품목명을 가져와 한줄 설명을 생성하고,
    설명 텍스트를 documents(임베딩 대상)로 하는 items 리스트로 변환.

    반환 형태: [{"id": "kamis_0", "document": "<설명>", "metadata": {"name": "<원래 품목명>"}}, ...]
    """
    if not UPSTAGE_API_KEY:
        raise RuntimeError("UPSTAGE_API_KEY가 .env에 없어서 설명을 생성할 수 없습니다.")

    names = get_kamis_names()
    print(f"\nKAMIS 품목 {len(names)}개에 대한 설명 생성 시작 (동시 {concurrency}개)...")

    descriptions = asyncio.run(
        _generate_descriptions_with_progress(names, concurrency=concurrency)
    )

    items = []
    for i, name in enumerate(names):
        desc = descriptions.get(name, "").strip()
        document_text = desc if desc else name  # 설명 생성 실패 시 이름으로 대체
        items.append({
            "id": f"kamis_{i}",
            "document": document_text,
            "metadata": {"name": name, "source": "kamis"},
        })

    return items


# ── 5. 실행 ─────────────────────────────────────────────────────────

def main():
    if not check_env_vars():
        sys.exit(1)

    delete_all_collections()

    print("\n── 결과 요약 ──")

    # KAMIS: 설명을 생성해서 그 설명 텍스트를 임베딩 대상으로 저장
    kamis_items = get_kamis_items_with_descriptions()
    save_items_to_chroma(kamis_items, collection_name=COLLECTION_NAME)

    # 참가격: 기존 방식 그대로 (품목명 자체를 임베딩)
    price_items = get_price_gokr_items()
    price_items = [{"id": f"pricegokr_{it['id']}", "document": it["name"]} for it in price_items]
    collection = save_items_to_chroma(price_items, collection_name=COLLECTION_NAME)

    print(f"\n최종 컬렉션 '{COLLECTION_NAME}' 총 {collection.count()}개 품목")

if __name__ == "__main__":
    main()
    test_similar_search("사과")