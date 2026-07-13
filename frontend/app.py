"""푸드 나침반 - 로컬 테스트용 Streamlit 챗봇 프론트엔드.

실행: streamlit run frontend/app.py
"""
import html
import json

import httpx
import streamlit as st

BACKEND_URL = "http://localhost:8000"

st.set_page_config(page_title="Food Compass", page_icon="🛒")
st.title("🛒 푸드 나침반")

# 좌우로 나뉜 말풍선을 위한 커스텀 CSS
st.markdown(
    """
    <style>
    .bubble-row {
        display: flex;
        width: 100%;
        margin: 6px 0;
    }
    .bubble-row.user { justify-content: flex-end; }
    .bubble-row.assistant { justify-content: flex-start; }

    .bubble {
        max-width: 70%;
        padding: 10px 14px;
        border-radius: 16px;
        line-height: 1.5;
        font-size: 15px;
        word-wrap: break-word;
        white-space: pre-wrap;
    }
    .bubble.user {
        background-color: #87CEEB;
        color: #FFFFFF;
        border-bottom-right-radius: 4px;
    }
    .bubble.assistant {
        background-color: #F1F1F3;
        color: #000000;
        border-bottom-left-radius: 4px;
    }
    .bubble.status {
        background-color: #F1F1F3;
        color: #888888;
        font-style: italic;
        border-bottom-left-radius: 4px;
    }
    .bubble.error {
        background-color: #FFE2E2;
        color: #B00020;
        border-bottom-left-radius: 4px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_bubble(role: str, content: str, variant: str = ""):
    """role에 맞춰 좌/우 정렬된 말풍선 HTML을 그린다."""
    css_class = variant or role
    safe_content = html.escape(content).replace("\n", "<br>")
    st.markdown(
        f'<div class="bubble-row {role}"><div class="bubble {css_class}">{safe_content}</div></div>',
        unsafe_allow_html=True,
    )


# 대화 기록 저장 (새로고침 전까지 유지됨)
if "messages" not in st.session_state:
    st.session_state.messages = []

# 이전 대화 내용 출력
for msg in st.session_state.messages:
    render_bubble(msg["role"], msg["content"])

# 사용자 입력창 (하단 고정)
query = st.chat_input("질문을 입력하세요 (예: 상추 지금 비싸?)")

if query:
    # 사용자 메시지 표시 + 기록 저장
    st.session_state.messages.append({"role": "user", "content": query})
    render_bubble("user", query)

    # AI 응답 자리 (스트리밍 중 계속 갱신됨)
    status_placeholder = st.empty()
    answer_placeholder = st.empty()
    final_answer = ""

    try:
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
                        with status_placeholder:
                            render_bubble("assistant", data["step"], variant="status")
                    elif event_type == "result":
                        status_placeholder.empty()
                        final_answer = data["answer"]
                        with answer_placeholder:
                            render_bubble("assistant", final_answer)
    except httpx.ConnectError:
        status_placeholder.empty()
        final_answer = "⚠️ 백엔드 서버에 연결할 수 없습니다. uvicorn 서버가 실행 중인지 확인해주세요."
        with answer_placeholder:
            render_bubble("assistant", final_answer, variant="error")

    # AI 메시지도 기록에 저장 (다음 렌더링에서도 계속 보이도록)
    st.session_state.messages.append({"role": "assistant", "content": final_answer})