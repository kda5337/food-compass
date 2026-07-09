"""LangGraph 노드 간에 주고받는 Pydantic 스키마 정의."""
from typing import Literal
from pydantic import BaseModel, Field


class ParseQueryInput(BaseModel):
    """사용자 자연어 질문 입력."""
    query: str = Field(..., description="사용자가 입력한 자연어 질문 (예: '상추 지금 비싸?')")


class ParseQuery(BaseModel):
    """Router LLM이 반환해야 하는 구조화 출력.
    parse_query 구조화 출력 스키마

    route:
      - price: 농수산물/식품 가격 조회 질문
      - off-topic: 가격 조회와 무관한 질문

    items:
      - route가 price이면 조회 대상 품목 리스트
      - route가 off-topic이면 빈 리스트 권장
    """
    
    intent: Literal["price", "off-topic"] = Field(
        ..., description="질문 분류 결과: 가격 판단 요청이면 'price', 그 외 잡담/무관 질문이면 'off-topic'"
    )
    items: list[str] = Field(
        default_factory=list,
        description="질문에서 추출한 품목명 목록 (예: ['상추']). off-topic이면 빈 리스트",
    )