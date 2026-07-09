"""
장바구니 물가 판단 에이전트 - 터미널 체험용 CLI
실행: .venv/Scripts/python.exe run.py
"""
from app.graph import compiled_graph
import asyncio

async def main():
    print("=" * 50)
    print("  장바구니 물가 판단 에이전트 (Day2 Mock)")
    print("  종료: 'q' 또는 'exit' 입력")
    print("=" * 50)

    while True:
        try:
            query = input("\n질문: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if query.lower() in ("q", "exit", "quit", "종료"):
            print("종료합니다.")
            break

        if not query:
            continue

        result = await compiled_graph.ainvoke({"user_query": query})
        print(f"\n[{result.get('route', '?').upper()}]")
        print(result.get("answer", "응답 없음"))


if __name__ == "__main__":
    asyncio.run(main())