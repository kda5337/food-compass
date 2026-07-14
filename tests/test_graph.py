
from app.graph import compiled_graph


class TestGraph:
    async def test_price_path_end_to_end(self):
        result = await compiled_graph.ainvoke({"user_query": "상추 지금 비싸?"})
        assert result["route"] == "price"
        assert result["answer"]  # LLM이 생성한 자유 문장이라 내용 대신 비어있지 않은지만 확인
        judgments = result.get("judgment", [])
        assert len(judgments) > 0
        assert judgments[0]["status"] in ("비쌈", "적정", "쌈")

    async def test_price_path_contains_item_name(self):
        result = await compiled_graph.ainvoke({"user_query": "배추 요즘 비싸?"})
        assert result["route"] == "price"
        assert "배추" in result["answer"]

    async def test_offtopic_path(self):
        result = await compiled_graph.ainvoke({"user_query": "안녕하세요"})
        assert result["route"] == "off-topic"
        assert "answer" in result
        assert "에이전트" in result["answer"]

    async def test_price_data_populated(self):
        result = await compiled_graph.ainvoke({"user_query": "오이 시세 어때?"})
        assert result["route"] == "price"
        assert len(result.get("price_data", [])) > 0

    async def test_judgment_populated(self):
        result = await compiled_graph.ainvoke({"user_query": "상추 비싸?"})
        assert result["route"] == "price"
        judgments = result.get("judgment", [])
        assert len(judgments) > 0
        assert "status" in judgments[0]
        assert "diff_pct" in judgments[0]

    async def test_scenario1_rice_vs_instant_rice(self):
        # [시나리오 1] 쌀(KAMIS) + 즉석밥(참가격) 조합은 judge_price가 아니라
        # compare_items 경로를 타야 함. Router가 "즉석밥"/"햇반" 중 어떤 표현으로
        # 추출하든(둘 다 item_alias.py에 매핑돼 있음) 통과해야 하므로 정확한 문자열
        # 대신 alias 후보군으로 검증.
        result = await compiled_graph.ainvoke(
            {"user_query": "쌀 사서 밥 짓는 거랑 햇반 사 먹는 거 뭐가 싸?"}
        )
        assert result["route"] == "price"
        comparison = result.get("comparison")
        assert comparison is not None
        assert comparison["raw_item"] == "쌀"
        assert comparison["processed_item"] in ("즉석밥", "햇반")
        assert comparison["raw_price_per_bowl"] > 0
        assert comparison["processed_price_per_bowl"] > 0
        assert comparison["cheaper_item"] in (comparison["raw_item"], comparison["processed_item"])
        assert comparison["raw_item"] in result["answer"]
        assert comparison["processed_item"] in result["answer"]
        # 이 조합은 judge_price를 건너뛰므로 judgment는 채워지지 않아야 함
        assert result.get("judgment", []) == []

    async def test_processed_price_multiple_matches(self):
        # [가공식품 단독 조회] KAMIS에 없는 품목("참치캔")은 judge_price/compare_items가
        # 아니라 search_processed_price 경로를 타야 함 — 매칭되는 여러 상품(동원/사조/오뚜기 등)
        # 을 전부 보여주고, 비쌈/적정 판정은 하지 않아야 함(judgment 비어있음).
        result = await compiled_graph.ainvoke({"user_query": "참치캔 얼마야?"})
        assert result["route"] == "price"
        processed = result.get("processed_prices")
        assert processed is not None
        assert len(processed) == 1
        assert processed[0]["found"] is True
        assert len(processed[0]["products"]) > 1  # 여러 브랜드/용량이 매칭돼야 함
        assert result.get("judgment", []) == []
        assert result.get("comparison") is None

    async def test_processed_price_not_found(self):
        # DB에 없는 가공식품은 임의로 비슷한 상품을 추천하지 않고 명확히 "없음" 안내해야 함
        result = await compiled_graph.ainvoke({"user_query": "유니콘사탕 얼마야?"})
        assert result["route"] == "price"
        processed = result.get("processed_prices")
        assert processed is not None
        assert processed[0]["found"] is False
        assert processed[0]["products"] == []

    async def test_processed_price_mixed_with_kamis_falls_back_to_judge(self):
        # [스코프 확인] KAMIS 품목 + 가공식품이 섞이면(예: "상추랑 참치캔") 이번 기능
        # 대상이 아니라 기존 judge_price 경로로 감 — 참치캔은 기존과 동일하게 "미지원"
        # 처리되어야 하고(회귀 없음), 상추는 정상적으로 판정되어야 함.
        result = await compiled_graph.ainvoke({"user_query": "상추랑 참치캔 가격 알려줘"})
        assert result["route"] == "price"
        assert result.get("processed_prices") is None
        judgments = result.get("judgment", [])
        statuses = {j["item_name"]: j["status"] for j in judgments}
        assert statuses.get("상추") in ("비쌈", "적정", "쌈")
        assert statuses.get("참치캔") == "미지원"
