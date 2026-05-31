"""LLM이 제안한 운동 항목을 RoutineExercise 컬럼으로 변환하는 헬퍼.

`load_calc.py`의 `get_recommended_weight_range` / `estimate_1rm`을 호출해
사용자 1RM과 목표(goal)에 맞는 weight_kg / reps_min / reps_max / sets / rest_seconds를 산출한다.

load_calc.py는 100% 커버리지 대상(CLAUDE.md §13)이므로 이 모듈에 분리해서
라우터에서 직접 1RM 보정 로직을 다루지 않도록 한다.
"""

from __future__ import annotations

from app.services.load_calc import RANGES, get_recommended_weight_range

# CLAUDE.md §11 목표별 권장 반복 범위
_REPS_BY_GOAL: dict[str, tuple[int, int]] = {
    "hypertrophy": (8, 12),
    "strength": (1, 5),
    "endurance": (15, 20),
    "rehabilitation": (20, 30),
    # weight_loss는 현재 load_calc.RANGES 미정의. 운동생리학 기준 고볼륨/저중량 endurance와 유사.
    "weight_loss": (15, 20),
}

# weight_loss → 권장 중량 매핑 (RANGES 미정의분 보완). endurance와 동일하게 처리한다.
_GOAL_TO_RANGE_KEY: dict[str, str] = {
    "hypertrophy": "hypertrophy",
    "strength": "strength",
    "endurance": "endurance",
    "rehabilitation": "rehabilitation",
    "weight_loss": "endurance",
}

# 목표별 권장 휴식 시간 (초). LLM 제안값을 무시하고 이 값을 사용한다.
# 근거: LLM은 운동별로 동일한 휴식 시간을 반복 제안하는 경향이 있어 신뢰할 수 없음.
# 운동생리학 기준: strength=고중량 회복 3분, hypertrophy=90초, endurance/weight_loss=45초, rehab=60초
_REST_BY_GOAL: dict[str, int] = {
    "strength": 180,
    "hypertrophy": 90,
    "endurance": 45,
    "weight_loss": 45,
    "rehabilitation": 60,
}

DEFAULT_SETS = 3


def _normalize_goal(goal):
    """대소문자/공백 정규화. 알 수 없는 값은 hypertrophy로 fallback."""
    if not goal:
        return "hypertrophy"
    g = goal.strip().lower()
    if g in _REPS_BY_GOAL:
        return g
    return "hypertrophy"


def _coerce_int(value, default=None):
    """LLM이 가끔 문자열로 숫자를 보내는 경우 안전하게 정수화. bool은 default로 취급."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def recommended_weight_kg(goal, user_1rm_kg):
    """사용자 1RM이 있으면 목표별 권장 범위의 중간값을 반환. 없으면 None.

    weight_kg는 nullable이며, 보조운동/1RM 미보유 운동은 사용자가 첫 세션 때 채운다.
    """
    if user_1rm_kg is None or user_1rm_kg <= 0:
        return None
    range_key = _GOAL_TO_RANGE_KEY.get(_normalize_goal(goal))
    if range_key is None or range_key not in RANGES:
        return None
    low, high = get_recommended_weight_range(user_1rm_kg, range_key)
    # 표시값은 2.5kg 단위로 반올림 (헬스장 표준 원판 최소단위)
    mid = (low + high) / 2.0
    return round(mid / 2.5) * 2.5


def derive_exercise_targets(
    *,
    goal,
    user_1rm_kg=None,
    llm_sets=None,
    llm_reps_min=None,
    llm_reps_max=None,
    llm_rest_seconds=None,  # 수신은 하되 사용하지 않음 (LLM 값 신뢰 불가)
):
    """LLM이 제안한 day-exercise 항목을 RoutineExercise 컬럼 dict로 변환.

    Args:
        goal: 1차 운동 목표 (대소문자 무관)
        user_1rm_kg: 해당 운동에 대한 사용자 1RM (없으면 None → weight_kg=None)
        llm_*: LLM 응답의 sets/reps_min/reps_max (str/int/None 모두 허용)
               llm_rest_seconds는 LLM이 모든 운동에 동일한 값을 반복 제안하므로 무시하고
               _REST_BY_GOAL 기반으로 목표별 고정값을 사용한다.

    Returns:
        {
            "sets": int,
            "reps_min": int,
            "reps_max": int,
            "rest_seconds": int,
            "weight_kg": float | None,
        }
    """
    g = _normalize_goal(goal)
    default_reps_min, default_reps_max = _REPS_BY_GOAL[g]

    # _coerce_int가 이미 default를 반환하므로 `or`로 falsy-fallback 하지 않는다.
    # (0 같은 falsy이지만 유효한 값을 default로 덮어쓰지 않기 위함)
    sets = _coerce_int(llm_sets, DEFAULT_SETS)
    reps_min = _coerce_int(llm_reps_min, default_reps_min)
    reps_max = _coerce_int(llm_reps_max, default_reps_max)
    # LLM 값 무시 — 목표별 운동생리학 기준값 사용
    rest_seconds = _REST_BY_GOAL[g]

    # 반복 범위 정합성: min > max인 경우 swap
    if reps_min > reps_max:
        reps_min, reps_max = reps_max, reps_min

    # 음수/0 방어
    sets = max(1, sets)
    reps_min = max(1, reps_min)
    reps_max = max(reps_min, reps_max)

    return {
        "sets": sets,
        "reps_min": reps_min,
        "reps_max": reps_max,
        "rest_seconds": rest_seconds,
        "weight_kg": recommended_weight_kg(g, user_1rm_kg),
    }
