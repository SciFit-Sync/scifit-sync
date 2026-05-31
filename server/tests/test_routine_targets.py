"""routine_targets.derive_exercise_targets 단위 테스트.

이 테스트는 RAG 파이프라인의 load_calc 통합 지점만 격리해서 검증한다:
LLM 응답의 sets/reps/rest_seconds 값과 사용자 1RM이 어떻게
RoutineExercise 컬럼 값으로 변환되는지.

load_calc.py 자체의 100% 커버리지는 tests/test_load_calc.py에서 유지된다.
"""

import pytest

from app.services.routine_targets import (
    _REST_BY_GOAL,
    DEFAULT_SETS,
    derive_exercise_targets,
    recommended_weight_kg,
)


class TestRecommendedWeightKg:
    """recommended_weight_kg: 1RM + 목표 → 권장 표시 중량."""

    def test_returns_none_when_no_1rm(self):
        assert recommended_weight_kg("hypertrophy", None) is None

    def test_returns_none_when_zero_1rm(self):
        assert recommended_weight_kg("hypertrophy", 0.0) is None

    def test_returns_none_when_negative_1rm(self):
        assert recommended_weight_kg("hypertrophy", -10.0) is None

    def test_hypertrophy_midpoint(self):
        # 100kg 1RM, hypertrophy 67~77% → 평균 72% = 72kg → 2.5kg 라운딩 = 72.5
        # load_calc 내부 round 처리: low=67.0, high=77.0, mid=72.0, /2.5=28.8 → round=29 → 29*2.5=72.5
        assert recommended_weight_kg("hypertrophy", 100.0) == 72.5

    def test_strength_midpoint(self):
        # 100kg 1RM, strength 85~95% → mid=90 → 90.0
        assert recommended_weight_kg("strength", 100.0) == 90.0

    def test_endurance_midpoint(self):
        # 100kg 1RM, endurance 50~65% → mid=57.5 → 2.5 단위 라운딩 = 57.5
        assert recommended_weight_kg("endurance", 100.0) == 57.5

    def test_rehabilitation_midpoint(self):
        # 100kg 1RM, rehabilitation 40~55% → mid=47.5 → 47.5
        assert recommended_weight_kg("rehabilitation", 100.0) == 47.5

    def test_weight_loss_falls_back_to_endurance(self):
        # weight_loss는 RANGES에 없음 → endurance 범위로 매핑
        assert recommended_weight_kg("weight_loss", 100.0) == 57.5

    def test_case_insensitive_goal(self):
        assert recommended_weight_kg("HYPERTROPHY", 100.0) == 72.5
        assert recommended_weight_kg("Strength", 100.0) == 90.0

    def test_unknown_goal_falls_back(self):
        # 알 수 없는 목표 → _normalize_goal이 hypertrophy로 fallback
        assert recommended_weight_kg("bulking_mode", 100.0) == 72.5

    def test_2_5kg_rounding(self):
        # 1RM=77kg, hypertrophy → low=51.59, high=59.29, mid=55.44 → /2.5=22.176 → round=22 → 55.0
        assert recommended_weight_kg("hypertrophy", 77.0) == 55.0

    def test_small_1rm(self):
        # 1RM=10kg, hypertrophy → mid=7.2 → /2.5=2.88 → round=3 → 7.5
        assert recommended_weight_kg("hypertrophy", 10.0) == 7.5


class TestDeriveExerciseTargets:
    """LLM 출력 + 1RM → RoutineExercise dict 변환."""

    def test_llm_sets_reps_passthrough_rest_goal_based(self):
        # llm_rest_seconds는 무시되고 목표별 고정값(_REST_BY_GOAL)이 사용됨
        result = derive_exercise_targets(
            goal="hypertrophy",
            user_1rm_kg=100.0,
            llm_sets=4,
            llm_reps_min=8,
            llm_reps_max=12,
            llm_rest_seconds=999,  # 무시되어야 함
        )
        assert result == {
            "sets": 4,
            "reps_min": 8,
            "reps_max": 12,
            "rest_seconds": _REST_BY_GOAL["hypertrophy"],  # 90
            "weight_kg": 72.5,
        }

    def test_no_1rm_yields_none_weight(self):
        result = derive_exercise_targets(
            goal="hypertrophy",
            user_1rm_kg=None,
            llm_sets=3,
            llm_reps_min=8,
            llm_reps_max=12,
        )
        assert result["weight_kg"] is None
        assert result["sets"] == 3

    def test_default_sets_when_llm_omits(self):
        result = derive_exercise_targets(goal="hypertrophy")
        assert result["sets"] == DEFAULT_SETS
        assert result["rest_seconds"] == _REST_BY_GOAL["hypertrophy"]

    def test_default_reps_match_goal_hypertrophy(self):
        result = derive_exercise_targets(goal="hypertrophy")
        assert result["reps_min"] == 8
        assert result["reps_max"] == 12

    def test_default_reps_match_goal_strength(self):
        result = derive_exercise_targets(goal="strength")
        assert result["reps_min"] == 1
        assert result["reps_max"] == 5

    def test_default_reps_match_goal_endurance(self):
        result = derive_exercise_targets(goal="endurance")
        assert result["reps_min"] == 15
        assert result["reps_max"] == 20

    def test_default_reps_match_goal_rehabilitation(self):
        result = derive_exercise_targets(goal="rehabilitation")
        assert result["reps_min"] == 20
        assert result["reps_max"] == 30

    def test_string_numbers_coerced(self):
        # LLM이 가끔 "8" 같은 문자열로 보내는 경우
        # llm_rest_seconds는 문자열이어도 무시되고 목표별 고정값이 사용됨
        result = derive_exercise_targets(
            goal="hypertrophy",
            llm_sets="4",
            llm_reps_min="10",
            llm_reps_max="15",
            llm_rest_seconds="120",  # 무시됨
        )
        assert result["sets"] == 4
        assert result["reps_min"] == 10
        assert result["reps_max"] == 15
        assert result["rest_seconds"] == _REST_BY_GOAL["hypertrophy"]  # 90

    def test_invalid_strings_fallback_to_defaults(self):
        result = derive_exercise_targets(
            goal="hypertrophy",
            llm_sets="four",
            llm_reps_min="N/A",
        )
        assert result["sets"] == DEFAULT_SETS
        assert result["reps_min"] == 8  # hypertrophy default

    def test_min_greater_than_max_swapped(self):
        result = derive_exercise_targets(
            goal="hypertrophy",
            llm_reps_min=12,
            llm_reps_max=8,
        )
        assert result["reps_min"] == 8
        assert result["reps_max"] == 12

    def test_negative_sets_clamped_to_one(self):
        result = derive_exercise_targets(goal="hypertrophy", llm_sets=-2)
        assert result["sets"] == 1

    def test_zero_sets_clamped_to_one(self):
        result = derive_exercise_targets(goal="hypertrophy", llm_sets=0)
        assert result["sets"] == 1

    def test_llm_rest_seconds_ignored(self):
        # llm_rest_seconds는 어떤 값이어도 무시되고 목표별 고정값이 반환됨
        result = derive_exercise_targets(goal="hypertrophy", llm_rest_seconds=-30)
        assert result["rest_seconds"] == _REST_BY_GOAL["hypertrophy"]

    def test_unknown_goal_falls_back_to_hypertrophy(self):
        result = derive_exercise_targets(goal="bulking_mode", user_1rm_kg=100.0)
        # hypertrophy default reps + weight
        assert result["reps_min"] == 8
        assert result["reps_max"] == 12
        assert result["weight_kg"] == 72.5

    def test_none_goal_falls_back(self):
        result = derive_exercise_targets(goal=None, user_1rm_kg=100.0)
        assert result["reps_min"] == 8
        assert result["weight_kg"] == 72.5

    def test_uppercase_goal_normalized(self):
        # 사용자가 보낸 "HYPERTROPHY"가 그대로 흘러와도 처리되어야 함
        result = derive_exercise_targets(goal="HYPERTROPHY", user_1rm_kg=100.0)
        assert result["reps_min"] == 8
        assert result["weight_kg"] == 72.5

    def test_strength_with_user_1rm(self):
        result = derive_exercise_targets(
            goal="strength",
            user_1rm_kg=140.0,  # 140 * 0.85=119, 140*0.95=133, mid=126 → /2.5=50.4 → round=50 → 125.0
        )
        assert result["weight_kg"] == 125.0

    def test_bool_sets_treated_as_default(self):
        # True/False가 LLM에서 흘러나오는 황당 케이스: bool은 int의 서브타입이지만 의도와 다름
        result = derive_exercise_targets(goal="hypertrophy", llm_sets=True)
        assert result["sets"] == DEFAULT_SETS

    @pytest.mark.parametrize(
        "goal,expected_low_reps,expected_high_reps",
        [
            ("hypertrophy", 8, 12),
            ("strength", 1, 5),
            ("endurance", 15, 20),
            ("rehabilitation", 20, 30),
            ("weight_loss", 15, 20),
        ],
    )
    def test_default_reps_for_all_goals(self, goal, expected_low_reps, expected_high_reps):
        result = derive_exercise_targets(goal=goal)
        assert result["reps_min"] == expected_low_reps
        assert result["reps_max"] == expected_high_reps

    @pytest.mark.parametrize(
        "goal,expected_rest",
        [
            ("strength", 180),
            ("hypertrophy", 90),
            ("endurance", 45),
            ("weight_loss", 45),
            ("rehabilitation", 60),
        ],
    )
    def test_rest_seconds_goal_based(self, goal, expected_rest):
        # llm_rest_seconds는 무시되고 목표별 고정값이 항상 반환됨
        result = derive_exercise_targets(goal=goal, llm_rest_seconds=999)
        assert result["rest_seconds"] == expected_rest
