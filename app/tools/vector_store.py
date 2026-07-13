"""ChromaDB 임베딩 모델 및 컬렉션 싱글톤 관리.

임베딩 모델은 모듈 로드 시 즉시 초기화(서버 프로세스당 1회).
Chroma 클라이언트/컬렉션은 최초 요청 시점에 지연 초기화 후 캐싱.
"""
from __future__ import annotations

import os

import chromadb
from chromadb.utils import embedding_functions

CHROMA_DB_PATH = "./data/chroma_db"
COLLECTION_NAME = "all_food_products"
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")

korean_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL_NAME
)
_collection = None


def get_collection():
    """Chroma 컬렉션을 최초 호출 시 1회 생성 후 캐싱해서 반환."""
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        _collection = client.get_collection(
            COLLECTION_NAME,
            embedding_function=korean_embedding_fn,
        )
    return _collection


