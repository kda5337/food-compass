"""푸드 나침반 - 로컬 테스트용 최소 Streamlit 프론트엔드.

실행: streamlit run frontend/app.py
"""
import json
import os

import httpx
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Food Compass", page_icon="🛒")
st.title("🛒 푸드 나침반")

query = st.text_input("질문을 입력하세요", placeholder="예: 상추 지금 비싸?")

if st.button("물어보기") and query.strip():
    status_box = st.empty()
    answer_box = st.empty()
    streamed_answer = ""

    with httpx.stream(
        "POST", f"{BACKEND_URL}/chat", json={"query": query}, timeout=30
    ) as response:
        event_type = None
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
                if event_type == "status":
                    status_box.info(data["step"])
                elif event_type == "token":
                    # LLM이 생성 중인 답변을 토큰 단위로 실시간 렌더링
                    status_box.empty()
                    streamed_answer += data["delta"]
                    answer_box.markdown(streamed_answer)
                elif event_type == "result":
                    status_box.empty()
                    answer_box.success(data["answer"])
