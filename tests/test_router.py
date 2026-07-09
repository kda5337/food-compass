import pytest

from app.graph.router import router_node


class TestRouterNode:
    def test_price_query_single_item(self):
        state = {"user_query": "상추 지금 비싸?"}
        result = router_node(state)
        assert result["route"] == "price"
        assert "상추" in result["items"]

    def test_price_query_multiple_items(self):
        state = {"user_query": "오이랑 당근 요즘 어때?"}
        result = router_node(state)
        assert result["route"] == "price"
        assert "오이" in result["items"]
        assert "당근" in result["items"]

    def test_offtopic_greeting(self):
        state = {"user_query": "안녕하세요"}
        result = router_node(state)
        assert result["route"] == "off-topic"
        assert result["items"] == []

    def test_offtopic_unrelated(self):
        state = {"user_query": "파이썬 공부 어떻게 해?"}
        result = router_node(state)
        assert result["route"] == "off-topic"

    def test_price_keyword_only(self):
        # 품목 없이 가격 키워드만 있는 경우
        state = {"user_query": "요즘 시세가 많이 올랐나요?"}
        result = router_node(state)
        assert result["route"] == "price"
