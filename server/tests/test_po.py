from app.services.po import calculate_increase, check_po_trigger


class TestCheckPOTrigger:
    """PO 트리거 조건 테스트."""

    def test_trigger_hypertrophy(self):
        assert check_po_trigger([12, 12], "hypertrophy") is True

    def test_no_trigger_one_session(self):
        assert check_po_trigger([12], "hypertrophy") is False

    def test_no_trigger_below_upper(self):
        assert check_po_trigger([10, 11], "hypertrophy") is False

    def test_no_trigger_only_last(self):
        assert check_po_trigger([10, 12], "hypertrophy") is False

    def test_no_trigger_only_second_to_last(self):
        assert check_po_trigger([12, 10], "hypertrophy") is False

    def test_trigger_strength(self):
        assert check_po_trigger([5, 5], "strength") is True

    def test_trigger_endurance(self):
        assert check_po_trigger([20, 20], "endurance") is True

    def test_trigger_rehabilitation(self):
        assert check_po_trigger([30, 30], "rehabilitation") is True

    def test_above_upper_triggers(self):
        assert check_po_trigger([15, 15], "hypertrophy") is True

    def test_empty_list(self):
        assert check_po_trigger([], "hypertrophy") is False

    def test_unknown_goal(self):
        assert check_po_trigger([10, 10], "unknown") is False

    def test_three_sessions_only_last_two_matter(self):
        assert check_po_trigger([8, 12, 12], "hypertrophy") is True

    def test_three_sessions_last_two_below(self):
        assert check_po_trigger([12, 12, 10], "hypertrophy") is False


class TestCalculateIncrease:
    """PO 증가량 계산 테스트."""

    def test_hypertrophy_cable(self):
        result = calculate_increase("cable", "hypertrophy", 50.0, 3)
        assert result["new_weight"] == 52.5
        assert result["new_sets"] == 3
        assert result["overflow"] is False
        assert result["message"] is None

    def test_hypertrophy_barbell(self):
        result = calculate_increase("barbell", "hypertrophy", 100.0, 3)
        assert result["new_weight"] == 105.0

    def test_strength_cable(self):
        result = calculate_increase("cable", "strength", 50.0, 3)
        assert result["new_weight"] == 55.0

    def test_endurance_cable(self):
        result = calculate_increase("cable", "endurance", 30.0, 3)
        assert result["new_weight"] == 31.25

    def test_rehabilitation_cable(self):
        result = calculate_increase("cable", "rehabilitation", 20.0, 3)
        assert result["new_weight"] == 21.25

    def test_max_stack_overflow(self):
        result = calculate_increase("cable", "hypertrophy", 48.0, 3, max_stack=50.0)
        assert result["new_weight"] == 50.0
        assert result["new_sets"] == 4
        assert result["overflow"] is True
        assert result["message"] is None

    def test_max_stack_no_overflow(self):
        result = calculate_increase("cable", "hypertrophy", 40.0, 3, max_stack=50.0)
        assert result["new_weight"] == 42.5
        assert result["overflow"] is False

    def test_sets_over_6_message(self):
        result = calculate_increase("cable", "hypertrophy", 49.0, 6, max_stack=50.0)
        assert result["new_sets"] == 7
        assert result["message"] == "더 무거운 기구 사용을 권장합니다"

    def test_sets_exactly_6_no_message(self):
        result = calculate_increase("cable", "hypertrophy", 49.0, 5, max_stack=50.0)
        assert result["new_sets"] == 6
        assert result["message"] is None

    def test_unknown_category_defaults(self):
        result = calculate_increase("unknown_cat", "hypertrophy", 50.0, 3)
        # unknown category falls back to default 1.25
        assert result["new_weight"] == 51.25

    def test_unknown_goal_defaults_to_endurance(self):
        result = calculate_increase("cable", "unknown_goal", 50.0, 3)
        assert result["new_weight"] == 51.25

    def test_no_max_stack(self):
        result = calculate_increase("cable", "hypertrophy", 1000.0, 3)
        assert result["new_weight"] == 1002.5
        assert result["overflow"] is False

    def test_machine_hypertrophy(self):
        result = calculate_increase("machine", "hypertrophy", 50.0, 3)
        assert result["new_weight"] == 52.5

    def test_dumbbell_hypertrophy(self):
        result = calculate_increase("dumbbell", "hypertrophy", 20.0, 3)
        assert result["new_weight"] == 22.5

    def test_bodyweight_strength(self):
        result = calculate_increase("bodyweight", "strength", 70.0, 3)
        assert result["new_weight"] == 75.0

    def test_increment_override_used(self):
        result = calculate_increase("cable", "hypertrophy", 50.0, 3, increment_override=3.0)
        assert result["new_weight"] == 53.0
        assert result["new_sets"] == 3
        assert result["overflow"] is False

    def test_increment_override_none_uses_hardcoded(self):
        result = calculate_increase("cable", "hypertrophy", 50.0, 3, increment_override=None)
        assert result["new_weight"] == 52.5

    def test_increment_override_with_max_stack_overflow(self):
        result = calculate_increase("cable", "hypertrophy", 49.0, 3, max_stack=50.0, increment_override=3.0)
        assert result["new_weight"] == 50.0
        assert result["overflow"] is True
