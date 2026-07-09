import pytest

from app.tools.judge import judge_price, parse_price


class TestParsePrice:
    def test_comma_string(self):
        assert parse_price("3,606") == 3606.0

    def test_missing_dash(self):
        assert parse_price("-") is None

    def test_empty_string(self):
        assert parse_price("") is None

    def test_plain_number(self):
        assert parse_price("1200") == 1200.0

    def test_whitespace_dash(self):
        assert parse_price(" - ") is None


class TestJudgePrice:
    def test_expensive(self):
        # 상추: 4500 vs 평년 2800 → +60.7% → 비쌈
        result = judge_price("4,500", "2,800")
        assert result.status == "비쌈"
        assert result.diff_pct > 10

    def test_appropriate_minus(self):
        # 배추: 2100 vs 평년 2300 → -8.7% → 적정
        result = judge_price("2,100", "2,300")
        assert result.status == "적정"
        assert -10 <= result.diff_pct <= 10

    def test_cheap(self):
        # 오이: 1200 vs 평년 1400 → -14.3% → 쌈
        result = judge_price("1,200", "1,400")
        assert result.status == "쌈"
        assert result.diff_pct < -10

    def test_missing_dpr1(self):
        # 깻잎: 당일가 결측 → 적정 + diff_pct=0.0
        result = judge_price("-", "1,600")
        assert result.status == "적정"
        assert result.diff_pct == 0.0

    def test_missing_dpr7(self):
        # 평년가 결측 → 적정 + diff_pct=0.0
        result = judge_price("4,500", "-")
        assert result.status == "적정"
        assert result.diff_pct == 0.0

    def test_appropriate_positive(self):
        # 당근: 2800 vs 평년 3100 → -9.7% → 적정
        result = judge_price("2,800", "3,100")
        assert result.status == "적정"
