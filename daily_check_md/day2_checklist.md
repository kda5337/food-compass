# Project Day2 (7/9) 체크리스트 — 장바구니 물가 판단 에이전트

> 목표: Mock 데이터로 "가격 판단형" 시나리오 1개를 처음부터 끝까지 동작시키기
> 완료 기준: `parse_query → get_raw_price(mock) → judge_price` 흐름이 pytest로 검증됨

---

## 0. 사전 준비

- [ ] 레포 폴더 구조 확정 및 생성
  - **내용**: `app/agents/`, `app/core/`, `app/prompts/`, `app/graph.py`, `app/api.py`, `app/schemas.py`, `app/vector_store.py`, `tests/` 폴더 생성
  - **Tool**: GitHub, VS Code
  - **참고**: 코드읽기 가이드의 Medical QA 예제 구조 그대로 재사용

- [ ] 가상환경 및 의존성 설치
  - **내용**: `langgraph`, `langchain`, `pydantic`, `fastapi`, `pytest`, `python-dotenv`, `chromadb`, `psycopg2-binary` 설치
  - **Tool**: `uv` 또는 `venv` + `pip`
  - **명령어 예시**: `uv add langgraph langchain pydantic fastapi pytest python-dotenv chromadb psycopg2-binary`

- [ ] `.env` / `.env.example`에 PostgreSQL 접속 정보 추가
  - **내용**: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` 5개 변수 추가
  - **Tool**: `.env.example`
  - **참고**: 로컬 개발 중엔 `POSTGRES_HOST=localhost`로 두고, Day4 배포 시 private 서버 IP로 교체

---

## 1. Tool Schema (Pydantic) 정의

- [ ] `parse_query` 입출력 스키마 정의
  - **내용**: 사용자 자연어 질문 → `{route: "price"|"off-topic", items: [str]}` 구조화 출력 스키마 작성
  - **Tool**: Pydantic (`BaseModel`)
  - **배경지식**: Pydantic 타입 힌트, LLM structured output(함수 호출/JSON 모드) 개념

- [ ] `get_raw_price` 입출력 스키마 정의
  - **내용**: 입력 `{item_name: str}` → 출력 `{item_name, dpr1(당일가), dpr5(전월가), dpr7(평년가), unit}` — KAMIS 응답 필드명 기준으로 설계
  - **Tool**: Pydantic
  - **참고**: 지난번 KAMIS 실제 응답 JSON 구조 그대로 반영 (`item_name`, `dpr1`~`dpr7` 필드)

- [ ] `judge_price` 입출력 스키마 정의
  - **내용**: 입력은 `get_raw_price` 출력 그대로 → 출력 `{status: "비쌈"|"적정"|"쌈", diff_pct: float}`
  - **Tool**: Pydantic

- [ ] (RAG 기본 구성과 연계) `search_substitute` 출력 스키마 초안
  - **내용**: 출력 `{substitutes: [str], source: str}` — Day5에 본격 구현되지만 스키마는 미리 잡아두기
  - **Tool**: Pydantic

---

## 2. Router 구현 (2분기: price / off-topic)

- [ ] Router 노드 프롬프트 작성
  - **내용**: 사용자 질문을 `price`/`off-topic`으로 분류 + 품목명 추출을 한 번의 LLM 호출로 처리하는 프롬프트 작성
  - **Tool**: `app/prompts/router_prompt.py` (또는 `.txt`)
  - **배경지식**: Few-shot 프롬프팅, structured output 유도 프롬프트 작성법

- [ ] Router 노드 함수 구현
  - **내용**: LLM 호출 → Pydantic 스키마로 파싱 → `route` 값에 따라 상태(state) 업데이트
  - **Tool**: LangGraph, Upstage Solar API (또는 이 단계에서는 Mock 함수로 대체 가능)
  - **배경지식**: LangGraph `StateGraph`, 노드(node) 함수 작성 패턴
  - **참고**: Day2는 실제 Solar 연동 전이므로, 고정 응답을 리턴하는 `mock_llm_router()` 함수로 먼저 구현해도 무방 (Day3에 실제 API로 교체)

- [ ] Off-topic 분기 처리
  - **내용**: `route == "off-topic"`이면 거절 응답 문자열 반환하고 그래프 종료
  - **Tool**: LangGraph conditional edge (`add_conditional_edges`)

---

## 3. ReAct Loop 구현 (price 경로)

- [ ] LangGraph `StateGraph` 골격 작성
  - **내용**: `State` 클래스 정의(질문, route, items, price_data, judgment, answer 필드 포함) + 노드 연결(`Router → get_raw_price → judge_price → 답변생성`)
  - **Tool**: LangGraph
  - **배경지식**: ReAct 패턴(Reasoning + Acting 반복), LangGraph의 `add_node`/`add_edge`/`add_conditional_edges` API

- [ ] `get_raw_price` 노드 구현 (Mock 버전)
  - **내용**: 실제 API 호출 대신, 고정된 Mock JSON(아래 4번 항목에서 준비)을 반환하는 함수로 구현
  - **Tool**: Python, LangGraph node
  - **참고**: 함수 시그니처는 Day3에 실제 KAMIS 호출로 그대로 교체 가능하도록 인터페이스 통일

- [ ] `judge_price` 노드 구현
  - **내용**: `dpr1`(당일가)을 `dpr7`(평년가) 대비 비교해 비쌈/적정/쌈 판정. 콤마 포함 문자열(`"3,606"`) 숫자 변환, `"-"` 결측치 처리 로직 포함
  - **Tool**: Python
  - **배경지식**: 문자열 전처리(콤마 제거, 타입 변환), 예외 처리(try/except)

- [ ] 답변 생성 노드 (텍스트만, SSE는 Day3)
  - **내용**: 판정 결과를 자연어 문장으로 조합해서 반환 (스트리밍은 아직 구현 안 해도 됨)
  - **Tool**: Python 문자열 포매팅 또는 간단한 LLM 호출

---

## 4. Mock 데이터로 가격 판단형 시나리오 검증

- [ ] KAMIS Mock 응답 JSON 파일 작성
  - **내용**: 지난번 실제로 확인했던 KAMIS 응답 구조 그대로, 상추 등 3~5개 품목의 고정 JSON을 `tests/fixtures/kamis_mock.json`으로 저장
  - **Tool**: JSON 파일
  - **참고**: 결측치(`"-"`) 케이스도 최소 1개 포함시켜서 예외 처리 테스트에 활용

- [ ] 시나리오 A 종단 실행 확인
  - **내용**: "상추 지금 비싸?" 입력 → Router(price 분기) → get_raw_price(mock) → judge_price → 답변까지 에러 없이 한 번에 실행되는지 수동 확인
  - **Tool**: Python 스크립트 또는 Jupyter/REPL

---

## 5. pytest로 핵심 흐름 테스트

- [ ] `judge_price` 단위 테스트 작성
  - **내용**: (a) 평년 대비 비쌈 케이스 (b) 적정 케이스 (c) 콤마 포함 문자열 처리 (d) `"-"` 결측치 처리 — 최소 4개 케이스
  - **Tool**: `pytest`
  - **명령어**: `pytest tests/test_judge_price.py -v`

- [ ] Router 분류 테스트 작성
  - **내용**: "상추 비싸?" → `price` 분기로, "안녕" 같은 잡담 → `off-topic` 분기로 가는지 확인 (Mock LLM 응답 기준)
  - **Tool**: `pytest`

- [ ] 전체 그래프 종단 테스트 작성
  - **내용**: Mock 데이터 기준으로 그래프 전체 실행 시 최종 답변에 특정 키워드(예: "비쌈" 또는 "적정")가 포함되는지 확인
  - **Tool**: `pytest`

---

## 6. RAG 기본 구성

- [ ] ChromaDB 로컬 인스턴스 셋업
  - **내용**: `chromadb.PersistentClient` 또는 in-memory 클라이언트로 컬렉션 하나 생성 (`substitutes` 등)
  - **Tool**: ChromaDB
  - **배경지식**: Vector DB 기본 개념(임베딩, 유사도 검색), ChromaDB Python API

- [ ] 문서 메타데이터 스키마 확정
  - **내용**: `item_name`, `category`, `season_months`, `content_type`, `source` 필드로 문서 저장 형식 확정
  - **Tool**: Python dict / JSON

- [ ] 샘플 문서 5~10개 임베딩 테스트
  - **내용**: 상추·깻잎·양배추 등 대체 품목 관계 문서 5~10개를 실제로 임베딩해서 넣어보고, 검색 쿼리 1개("상추 대체품")로 결과가 나오는지 확인
  - **Tool**: ChromaDB, 임베딩 모델(Upstage Embedding API 또는 오픈소스 `sentence-transformers`)
  - **참고**: 본격적인 문서 30~50개 구축은 Day5에 진행. 오늘은 파이프라인이 동작하는지만 확인

---

## 7. 가격 캐시 DB (PostgreSQL) 구성 — 신규 추가

> 배경: ChromaDB는 "의미 유사도 검색"(대체품 추천) 전용으로만 쓰고, API 실패 시 Fallback용 가격 캐시는
> 정확한 키 조회가 필요해 별도 PostgreSQL에 저장하기로 결정. private DB 서버에 ChromaDB와 나란히 구성.

- [ ] `docker-compose.db.yml` 작성 (private 서버 전용)
  - **내용**: `chromadb`, `postgres` 두 서비스를 정의. 로컬 개발 중엔 이 파일을 로컬에서 그대로 띄워서 테스트
  - **Tool**: Docker Compose
  - **참고**: 앱 서버용 `docker-compose.yml`과는 분리해서 관리 (나중에 private/public 서버 분리 배포 시 이 파일만 private 서버로)

- [ ] `db/init.sql` 작성 — `price_cache` 테이블 스키마
  - **내용**: `item_name`(PK), `source`, `price_data`(JSONB), `cached_at` 컬럼으로 테이블 생성 + `cached_at` 인덱스
  - **Tool**: PostgreSQL, SQL
  - **배경지식**: JSONB 컬럼 개념(스키마 유연성), `ON CONFLICT ... DO UPDATE`(upsert) 문법

- [ ] `app/tools/price_cache.py` 구현
  - **내용**: `save_price_cache(item_name, source, price_data)` / `get_price_cache(item_name, max_age_hours)` 두 함수 작성
  - **Tool**: `psycopg2`
  - **배경지식**: DB 커넥션 관리(connect/commit/close), upsert 쿼리

- [ ] 로컬에서 Postgres 컨테이너 띄우고 save/get 왕복 테스트
  - **내용**: `docker compose -f docker-compose.db.yml up -d` 실행 후, 더미 데이터로 `save_price_cache` → `get_price_cache` 호출해서 값이 그대로 돌아오는지 확인
  - **Tool**: Docker, Python REPL
  - **참고**: 실제 `get_raw_price`에 try/except로 연결해서 Fallback으로 동작시키는 건 Day3(실 API 연동) 작업. 오늘은 캐시 저장/조회 자체만 동작 확인하면 충분

---

## 진행 체크 (팀 공유용)

| 담당자 | 담당 파트 | 완료 여부 |
|---|---|---|
| | Tool Schema + Router | [ ] |
| | ReAct Loop + Mock 검증 | [ ] |
| | pytest 테스트 | [ ] |
| | RAG 기본 구성 | [ ] |
| | 가격 캐시 DB (PostgreSQL) 구성 | [ ] |

**Day2 완료 기준**: 위 체크리스트가 전부 체크되고, `pytest` 전체 실행 시 에러 없이 통과하는 상태로 하루를 마감합니다.
