'''
import chromadb
from chromadb.config import Settings

# Chroma 클라이언트 생성
client = chromadb.PersistentClient(path="./chroma_db")

# 컬렉션 생성
collection = client.get_or_create_collection(name="connection-test")

# 문서 추가
collection.add(
    documents=["챗GPT는 대형 언어 모델이다", "한국의 수도는 서울이다"],
    ids=["doc1", "doc2"],
    metadatas=[{"source": "test1"}, {"source": "test2"}]
)

# 검색 (쿼리와 가장 유사한 문서 반환)
results = collection.query(
    query_texts=["서울의 수도는 어디야?"],
    n_results=1
)

print(results)
'''
import chromadb
from chromadb.config import Settings

# 서비스 URL과 API 토큰을 사용하여 Chroma 클라이언트 생성
client = chromadb.HttpClient(
    host="https://chroma-mnnxrvri3q-du.a.run.app",
    port=443,
    ssl=True,
    settings=Settings(
        chroma_client_auth_provider="chromadb.auth.token_authn.TokenAuthClientProvider",
        chroma_client_auth_credentials="abcdefghijklmnopqrstuvwxyz",
        anonymized_telemetry=False
    )
)
