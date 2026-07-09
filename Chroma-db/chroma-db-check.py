import chromadb
from pprint import pprint

client = chromadb.PersistentClient(path="./chroma_db")

print("=== 컬렉션 목록 ===")
collections = client.list_collections()

for collection in collections:
    print("-", collection.name)

print("\n=== connection-test 데이터 ===")
collection = client.get_collection(name="connection-test")

print("저장된 문서 개수:", collection.count())

data = collection.get(
    include=["documents", "metadatas"]
)

pprint(data)