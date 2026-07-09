import pytest

from app.graph import compiled_graph


class TestGraph:
    def test_price_path_end_to_end(self):
        result = compiled_graph.invoke({"user_query": "상추 지금 비싸?"})
        assert result["route"] == "price"
        assert "answer" in result
        assert any(kw in result["answer"] for kw in ["비쌈", "적정", "쌈"])

    def test_price_path_contains_item_name(self):
        result = compiled_graph.invoke({"user_query": "배추 요즘 비싸?"})
        assert result["route"] == "price"
        assert "배추" in result["answer"]

    def test_offtopic_path(self):
        result = compiled_graph.invoke({"user_query": "안녕하세요"})
        assert result["route"] == "off-topic"
        assert "answer" in result
        assert "에이전트" in result["answer"]

    def test_price_data_populated(self):
        result = compiled_graph.invoke({"user_query": "오이 시세 어때?"})
        assert result["route"] == "price"
        assert len(result.get("price_data", [])) > 0

    def test_judgment_populated(self):
        result = compiled_graph.invoke({"user_query": "상추 비싸?"})
        assert result["route"] == "price"
        judgments = result.get("judgment", [])
        assert len(judgments) > 0
        assert "status" in judgments[0]
        assert "diff_pct" in judgments[0]
