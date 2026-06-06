"""Progressive Overload 엔진.

트리거: 목표 rep 상단을 연속 2세션 달성.
미결정 사항:
  - D-11: rehabilitation 목표의 PO 전략 → 보수적 기본값 1.25kg
재설계: 증분 분류 축이 equipment_type(5종) → exercise.load_mode(10종)으로 전환.
  cardio는 PO 대상이 아님(호출부에서 제외).
"""

REP_UPPER_BOUNDS: dict[str, int] = {
    "hypertrophy": 12,
    "strength": 5,
    "endurance": 20,
    "rehabilitation": 30,
}

# load_mode별/목표별 중량 증가량 (kg)
# 재설계: equipment_type → exercise.load_mode 기준. cardio는 PO 대상 아님(호출부에서 제외).
# family 규칙 (CLAUDE.md §11 PO표):
#   barbell-family  (barbell/ez_barbell/trap_bar)         → barbell 증분
#   free-added-family (dumbbell/kettlebell/band/weighted/bodyweight) → dumbbell 증분
#   machine-family  (cable/machine)                       → cable 증분
INCREASE: dict[str, dict[str, float]] = {
    "hypertrophy": {
        # machine-family
        "cable": 2.5,
        "machine": 2.5,
        # barbell-family
        "barbell": 5.0,
        "ez_barbell": 5.0,
        "trap_bar": 5.0,
        # free-added-family
        "dumbbell": 2.5,
        "kettlebell": 2.5,
        "band": 2.5,
        "weighted": 2.5,
        "bodyweight": 2.5,
    },
    "strength": {
        "cable": 5.0,
        "machine": 5.0,
        "barbell": 5.0,
        "ez_barbell": 5.0,
        "trap_bar": 5.0,
        "dumbbell": 5.0,
        "kettlebell": 5.0,
        "band": 5.0,
        "weighted": 5.0,
        "bodyweight": 5.0,
    },
    "endurance": {
        "cable": 1.25,
        "machine": 1.25,
        "barbell": 1.25,
        "ez_barbell": 1.25,
        "trap_bar": 1.25,
        "dumbbell": 1.25,
        "kettlebell": 1.25,
        "band": 1.25,
        "weighted": 1.25,
        "bodyweight": 1.25,
    },
    # D-11: rehabilitation PO 전략 미정 → 보수적 기본값
    "rehabilitation": {
        "cable": 1.25,
        "machine": 1.25,
        "barbell": 1.25,
        "ez_barbell": 1.25,
        "trap_bar": 1.25,
        "dumbbell": 1.25,
        "kettlebell": 1.25,
        "band": 1.25,
        "weighted": 1.25,
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

    Args:
        category: 운동의 load_mode (barbell/ez_barbell/trap_bar/dumbbell/kettlebell/
                  band/weighted/bodyweight/cable/machine).
                  인자명은 하위 호환을 위해 category로 유지하나 실제로는 load_mode 값을 받는다.
                  cardio는 호출부에서 제외되어 이 함수에 도달하지 않는다.
        goal: 운동 목표 (hypertrophy/strength/endurance/rehabilitation)
        current_weight: 현재 세션의 최대 중량 (kg)
        current_sets: 현재 세션의 세트 수
        max_stack: 기구의 최대 스택 중량 (kg). 프리웨이트는 None.

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
