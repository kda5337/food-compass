"""LangGraph 노드 간에 주고받는 Pydantic 스키마 정의."""
from typing import Literal
from pydantic import BaseModel, Field


class ParseQueryInput(BaseModel):
    """사용자 자연어 질문 입력."""
    query: str = Field(..., description="사용자가 입력한 자연어 질문 (예: '상추 지금 비싸?')")


class ParseQuery(BaseModel):
    """Router LLM이 반환해야 하는 구조화 출력.
    parse_query 구조화 출력 스키마

    intent:
      - price: 가격·시세 조회만 필요 (예: "상추 얼마야?")
      - knowledge: 가격 무관, 보관법·대체품 등 지식만 필요 (예: "상추 보관법 알려줘")
      - hybrid: 가격 판정 + 비쌈 시 대체품 추천 복합 (예: "상추 비싸면 대체품 알려줘")
      - off-topic: 가격/식품과 무관한 질문

    items:
      - off-topic이 아니면 조회/언급 대상 품목 리스트
      - off-topic이면 빈 리스트 권장
    """

    intent: Literal["price", "knowledge", "hybrid", "off-topic"] = Field(
        ..., description="질문 분류 결과: price/knowledge/hybrid/off-topic 중 하나"
    )
    items: list[str] = Field(
        default_factory=list,
        description="질문에서 추출한 품목명 목록 (예: ['상추']). off-topic이면 빈 리스트",
    )