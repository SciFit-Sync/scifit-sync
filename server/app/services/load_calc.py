from app.core.exceptions import ValidationError

RANGES: dict[str, tuple[float, float]] = {
    "hypertrophy": (0.67, 0.77),
    "strength": (0.85, 0.95),
    "endurance": (0.50, 0.65),
    "rehabilitation": (0.40, 0.55),
}


def calculate_effective_weight(
    equipment_type: str,
    *,
    stack: float | None = None,
    added: float | None = None,
    body_weight: float | None = None,
    pulley_ratio: float = 1.0,
    bar_weight_kg: float | None = None,
    has_weight_assist: bool = False,
) -> float:
    """도르래 비율 보정을 적용한 실효 부하를 계산한다."""
    match equipment_type:
        case "cable" | "machine":
            s = stack or 0.0
            return s * pulley_ratio + (bar_weight_kg or 0.0)
        case "barbell":
            return (bar_weight_kg or 0.0) + (added or 0.0)
        case "dumbbell":
            return added or 0.0
        case "bodyweight":
            bw = body_weight or 0.0
            if has_weight_assist:
                return bw - (stack or 0.0)
            return bw + (added or 0.0)
        case _:
            raise ValidationError(
                message=f"알 수 없는 equipment_type입니다: {equipment_type}",
                details={"equipment_type": equipment_type},
            )


def estimate_1rm(effective_weight: float, reps: int) -> float:
    """Epley 공식으로 1RM을 추정한다."""
    if reps < 0:
        raise ValidationError(
            message="반복 횟수는 0 이상이어야 합니다",
            details={"reps": reps},
        )
    if reps == 0:
        return effective_weight
    return effective_weight * (1 + reps / 30)


def get_recommended_weight_range(one_rm: float, goal: str) -> tuple[float, float]:
    """목표에 따른 권장 중량 범위를 반환한다."""
    if goal not in RANGES:
        raise ValidationError(
            message=f"알 수 없는 운동 목표입니다: {goal}",
            details={"goal": goal},
        )
    low_pct, high_pct = RANGES[goal]
    return (round(one_rm * low_pct, 2), round(one_rm * high_pct, 2))
