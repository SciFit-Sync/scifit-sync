import pytest

from app.core.exceptions import ValidationError
from app.services.load_calc import (
    calculate_effective_weight,
    estimate_1rm,
    get_recommended_weight_range,
)


class TestCalculateEffectiveWeight:
    """calculate_effective_weight: 5개 카테고리 + 경계값 테스트."""

    def test_cable_with_pulley_ratio(self):
        result = calculate_effective_weight("cable", stack=50.0, pulley_ratio=2.0, bar_weight_kg=5.0)
        assert result == 105.0  # 50 * 2.0 + 5.0

    def test_cable_default_ratio(self):
        result = calculate_effective_weight("cable", stack=40.0)
        assert result == 40.0  # 40 * 1.0 + 0

    def test_machine_with_bar_weight(self):
        result = calculate_effective_weight("machine", stack=30.0, pulley_ratio=1.5, bar_weight_kg=10.0)
        assert result == 55.0  # 30 * 1.5 + 10

    def test_machine_no_optional(self):
        result = calculate_effective_weight("machine", stack=20.0)
        assert result == 20.0

    def test_barbell(self):
        result = calculate_effective_weight("barbell", bar_weight_kg=20.0, added=60.0)
        assert result == 80.0

    def test_barbell_no_added(self):
        result = calculate_effective_weight("barbell", bar_weight_kg=20.0)
        assert result == 20.0

    def test_barbell_no_bar_weight(self):
        result = calculate_effective_weight("barbell", added=40.0)
        assert result == 40.0

    def test_dumbbell(self):
        result = calculate_effective_weight("dumbbell", added=20.0)
        assert result == 20.0

    def test_dumbbell_no_added(self):
        result = calculate_effective_weight("dumbbell")
        assert result == 0.0

    def test_bodyweight_no_assist(self):
        result = calculate_effective_weight("bodyweight", body_weight=70.0, added=10.0)
        assert result == 80.0

    def test_bodyweight_with_assist(self):
        result = calculate_effective_weight("bodyweight", body_weight=70.0, stack=20.0, has_weight_assist=True)
        assert result == 50.0  # 70 - 20

    def test_bodyweight_no_added_no_body(self):
        result = calculate_effective_weight("bodyweight")
        assert result == 0.0

    def test_cable_none_stack(self):
        result = calculate_effective_weight("cable")
        assert result == 0.0

    def test_unknown_category_raises(self):
        with pytest.raises(ValidationError, match="알 수 없는 equipment_type"):
            calculate_effective_weight("unknown_type")


class TestEstimate1RM:
    """estimate_1rm: Epley 공식 테스트."""

    def test_standard_case(self):
        result = estimate_1rm(100.0, 10)
        assert abs(result - 133.33) < 0.01

    def test_one_rep(self):
        result = estimate_1rm(100.0, 1)
        assert abs(result - 103.33) < 0.01

    def test_zero_reps(self):
        result = estimate_1rm(100.0, 0)
        assert result == 100.0

    def test_negative_reps_raises(self):
        with pytest.raises(ValidationError, match="0 이상"):
            estimate_1rm(100.0, -1)

    def test_high_reps(self):
        result = estimate_1rm(50.0, 30)
        assert result == 100.0  # 50 * (1 + 30/30) = 100

    def test_zero_weight(self):
        result = estimate_1rm(0.0, 10)
        assert result == 0.0


class TestGetRecommendedWeightRange:
    """get_recommended_weight_range: 목표별 범위 테스트."""

    def test_hypertrophy(self):
        low, high = get_recommended_weight_range(100.0, "hypertrophy")
        assert low == 67.0
        assert high == 77.0

    def test_strength(self):
        low, high = get_recommended_weight_range(100.0, "strength")
        assert low == 85.0
        assert high == 95.0

    def test_endurance(self):
        low, high = get_recommended_weight_range(100.0, "endurance")
        assert low == 50.0
        assert high == 65.0

    def test_rehabilitation(self):
        low, high = get_recommended_weight_range(100.0, "rehabilitation")
        assert low == 40.0
        assert high == 55.0

    def test_unknown_goal_raises(self):
        with pytest.raises(ValidationError, match="알 수 없는 운동 목표"):
            get_recommended_weight_range(100.0, "unknown")

    def test_zero_1rm(self):
        low, high = get_recommended_weight_range(0.0, "hypertrophy")
        assert low == 0.0
        assert high == 0.0
