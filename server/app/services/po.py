"""Progressive Overload 엔진.

트리거: 목표 rep 상단을 연속 2세션 달성.
미결정 사항:
  - D-11: rehabilitation 목표의 PO 전략 → 보수적 기본값 1.25kg
  - D-12: machine/dumbbell/bodyweight 증가량 → cable과 동일 기본값
"""

REP_UPPER_BOUNDS: dict[str, int] = {
    "hypertrophy": 12,
    "strength": 5,
    "endurance": 20,
    "rehabilitation": 30,
}

# 카테고리별/목표별 중량 증가량 (kg)
# D-12: machine/dumbbell/bodyweight는 cable과 동일한 기본값 사용
INCREASE: dict[str, dict[str, float]] = {
    "hypertrophy": {
        "cable": 2.5,
        "machine": 2.5,
        "barbell": 5.0,
        "dumbbell": 2.5,
        "bodyweight": 2.5,
    },
    "strength": {
        "cable": 5.0,
        "machine": 5.0,
        "barbell": 5.0,
        "dumbbell": 5.0,
        "bodyweight": 5.0,
    },
    "endurance": {
        "cable": 1.25,
        "machine": 1.25,
        "barbell": 1.25,
        "dumbbell": 1.25,
        "bodyweight": 1.25,
    },
    # D-11: rehabilitation PO 전략 미정 → 보수적 기본값
    "rehabilitation": {
        "cable": 1.25,
        "machine": 1.25,
        "barbell": 1.25,
        "dumbbell": 1.25,
        "bodyweight": 1.25,
    },
}


def check_po_trigger(
    recent_max_reps: list[int],
    goal: str,
) -> bool:
    """최근 세션들의 최대 reps를 확인하여 PO 트리거 여부를 판단한다.

    Args:
        recent_max_reps: 최근 세션 순서대로의 최대 반복 횟수 리스트 (최소 2개)
        goal: 운동 목표

    Returns:
        True이면 중량 증가 필요
    """
    if goal not in REP_UPPER_BOUNDS:
        return False
    upper = REP_UPPER_BOUNDS[goal]
    if len(recent_max_reps) < 2:
        return False
    return recent_max_reps[-1] >= upper and recent_max_reps[-2] >= upper


def calculate_increase(
    category: str,
    goal: str,
    current_weight: float,
    current_sets: int,
    max_stack: float | None = None,
    increment_override: float | None = None,
) -> dict:
    """PO 트리거 시 증가량을 계산한다.

    Returns:
        {
            "new_weight": float,
            "new_sets": int,
            "overflow": bool,
            "message": str | None,
        }
    """
    goal_map = INCREASE.get(goal, INCREASE["endurance"])
    increment = increment_override if increment_override is not None else goal_map.get(category, 1.25)

    new_weight = current_weight + increment
    new_sets = current_sets
    overflow = False
    message = None

    if max_stack is not None and new_weight > max_stack:
        new_weight = max_stack
        new_sets = current_sets + 1
        overflow = True

        if new_sets > 6:
            message = "더 무거운 기구 사용을 권장합니다"

    return {
        "new_weight": new_weight,
        "new_sets": new_sets,
        "overflow": overflow,
        "message": message,
    }
