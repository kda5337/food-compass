from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.graph import compiled_graph
from app.tools.price_cache import ping as db_ping

router = APIRouter()

# 그래프 노드 완료 직후 다음 단계를 안내하는 상태 메시지
# (checklist 6번 SSE 이벤트 구조 참고: 의도 분류 중 → 가격 조회 중 → 판정 중 → result → done)
_NEXT_STEP_STATUS = {
    "router": "가격 조회 중...",
    "get_raw_price": "판정 중...",
}


class ChatRequest(BaseModel):
    query: str


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


@router.post("/chat")
async def chat(request: ChatRequest):
    async def event_generator():
        yield _sse("status", {"step": "의도 분류 중..."})

        state: dict = {"user_query": request.query}
        async for chunk in compiled_graph.astream(state, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                state.update(node_output)
                if node_name == "router" and state.get("route") != "price":
                    continue
                next_status = _NEXT_STEP_STATUS.get(node_name)
                if next_status:
                    yield _sse("status", {"step": next_status})

        yield _sse("result", {"answer": state.get("answer", "")})
        yield _sse("done", {})

    return EventSourceResponse(event_generator())


@router.get("/health")
async def health():
    db_status = "connected" if db_ping() else "disconnected"
    return {"status": "ok", "db": db_status}
