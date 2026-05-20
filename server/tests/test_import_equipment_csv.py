"""import_equipment_csv.py 핵심 파서 단위 테스트.

_parse_weight_str, _parse_pattern, _parse_stack_weight 함수 검증.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from import_equipment_csv import _parse_pattern, _parse_stack_weight, _parse_weight_str


class TestParseWeightStr:
    def test_uniform_kg(self):
        val, unit = _parse_weight_str("5kg")
        assert val == 5.0
        assert unit == "kg"

    def test_uniform_lb(self):
        val, unit = _parse_weight_str("10lb")
        assert val == 10.0
        assert unit == "lb"

    def test_decimal_kg(self):
        val, unit = _parse_weight_str("2.5kg")
        assert val == 2.5
        assert unit == "kg"

    def test_null_string(self):
        val, unit = _parse_weight_str("null")
        assert val is None
        assert unit is None

    def test_empty_string(self):
        val, unit = _parse_weight_str("")
        assert val is None
        assert unit is None

    def test_question_mark(self):
        val, unit = _parse_weight_str("?")
        assert val is None
        assert unit is None

    def test_no_unit(self):
        val, unit = _parse_weight_str("120")
        assert val == 120.0
        assert unit is None

    def test_case_insensitive(self):
        val, unit = _parse_weight_str("20KG")
        assert val == 20.0
        assert unit == "kg"


class TestParsePattern:
    def test_single_segment(self):
        result, unit = _parse_pattern("10lb*5", "lb")
        assert unit == "lb"
        assert result == {"pattern": [{"from": 1, "to": 5, "value": 10.0}]}

    def test_multi_segment(self):
        result, unit = _parse_pattern("10lb*5, 15lb*10", "lb")
        assert unit == "lb"
        assert result["pattern"] == [
            {"from": 1, "to": 5, "value": 10.0},
            {"from": 6, "to": 15, "value": 15.0},
        ]

    def test_default_unit_fallback(self):
        result, unit = _parse_pattern("10*5", "kg")
        assert unit == "kg"
        assert result["pattern"][0]["value"] == 10.0

    def test_zero_count_rejected(self):
        result, unit = _parse_pattern("10kg*0", "kg")
        assert result is None
        assert unit is None

    def test_invalid_segment_rejected(self):
        result, unit = _parse_pattern("abc", "kg")
        assert result is None
        assert unit is None

    def test_from_increments_correctly(self):
        result, _ = _parse_pattern("5kg*3, 10kg*2", "kg")
        assert result["pattern"][0] == {"from": 1, "to": 3, "value": 5.0}
        assert result["pattern"][1] == {"from": 4, "to": 5, "value": 10.0}


class TestParseStackWeight:
    def test_uniform_value(self):
        result, unit = _parse_stack_weight("5kg", "kg")
        assert result == {"value": 5.0}
        assert unit == "kg"

    def test_null_input(self):
        result, unit = _parse_stack_weight("null", "kg")
        assert result is None
        assert unit is None

    def test_empty_input(self):
        result, unit = _parse_stack_weight("", "kg")
        assert result is None
        assert unit is None

    def test_pattern_input(self):
        result, unit = _parse_stack_weight("10lb*5, 15lb*10", "lb")
        assert "pattern" in result
        assert unit == "lb"

    def test_unknown_format_returns_none(self):
        result, unit = _parse_stack_weight("???", "kg")
        assert result is None
        assert unit is None
