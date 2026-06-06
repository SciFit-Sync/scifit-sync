from app.core.exceptions import ValidationError

RANGES: dict[str, tuple[float, float]] = {
    "hypertrophy": (0.67, 0.77),
    "strength": (0.85, 0.95),
    "endurance": (0.50, 0.65),
    "rehabilitation": (0.40, 0.55),
}

# 프리웨이트 load_mode → 바/레버 기본 무게(kg).
# 출처: docs/handoff/workoutx-raw/freeweight_load_modes.csv (D8: ez/trap 별도 바 무게).
FREEWEIGHT_BAR_KG: dict[str, float] = {
    "barbell": 20.0,
    "ez_barbell": 10.0,
    "trap_bar": 25.0,
    "dumbbell": 0.0,  # 바 무게 없음 — added만
    "kettlebell": 0.0,  # added만
    "band": 0.0,  # added(가변), 표준 무게 없음
}

# 전 헬스장 항상 가용(baseline) load_mode 집합 — routine_exercises.equipment_id=NULL.
FREEWEIGHT_MODES: frozenset[str] = frozenset(
    {"barbell", "ez_barbell", "trap_bar", "dumbbell", "bodyweight", "weighted", "kettlebell", "band"}
)
# gym_equipments 등록 실물로만 가용 — exercise_equipment ⋈ gym_equipments 필터 대상.
MACHINE_MODES: frozenset[str] = frozenset({"cable", "machine"})


def calculate_effective_weight(
    load_mode: str,
    *,
    stack: float | None = None,
    added: float | None = None,
    body_weight: float | None = None,
    pulley_ratio: float = 1.0,
    bar_weight: float | None = None,
    has_weight_assist: bool = False,
) -> float:
    """운동의 load_mode 기준 실효 부하(kg)를 계산한다.

    프리웨이트는 모듈 상수(FREEWEIGHT_BAR_KG)로, cable/machine은 실물 equipment 행의
    pulley_ratio/stack/bar_weight/has_weight_assist를 사용한다.
    """
    a = added or 0.0
    bw = body_weight or 0.0
    match load_mode:
        case "cable" | "machine":
            ratio = pulley_ratio if pulley_ratio else 1.0
            s = (stack or 0.0) / ratio
            # G3: 어시스티드 머신(Assisted Dip/Chin 등)은 스택이 체중을 상쇄한다.
            if has_weight_assist:
                return bw - s
            return s + (bar_weight or 0.0)
        case "barbell" | "ez_barbell" | "trap_bar":
            return FREEWEIGHT_BAR_KG[load_mode] + a
        case "dumbbell" | "kettlebell" | "band":
            return a
        case "bodyweight":
            # 가중 변형(가중 풀업/딥 등)은 load_mode='weighted'로 분리된다(D13).
            return bw + a
        case "weighted":
            return bw + a
        case "cardio":
            return 0.0  # 부하 개념 없음
        case _:
            raise ValidationError(
                message=f"알 수 없는 load_mode입니다: {load_mode}",
                details={"load_mode": load_mode},
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


def effective_to_stack_weight(
    effective_kg: float,
    load_mode: str,
    pulley_ratio: float = 1.0,
    bar_weight: float | None = None,
) -> float | None:
    """실효 부하(근육 하중) → 머신 스택 설정값 역변환.

    cable/machine만 stack = (effective - bar_weight) * pulley_ratio.
    프리웨이트(barbell/ez_barbell/trap_bar/dumbbell/bodyweight/weighted/kettlebell/band)와
    cardio는 None 반환 (effective를 그대로 표시값으로 사용).
    """
    if load_mode in MACHINE_MODES:
        bw = bar_weight or 0.0
        return max((effective_kg - bw) * max(pulley_ratio, 0.01), 0.0)
    return None


def get_recommended_weight_range(one_rm: float, goal: str) -> tuple[float, float]:
    """목표에 따른 권장 중량 범위를 반환한다."""
    if goal not in RANGES:
        raise ValidationError(
            message=f"알 수 없는 운동 목표입니다: {goal}",
            details={"goal": goal},
        )
    low_pct, high_pct = RANGES[goal]
    return (round(one_rm * low_pct, 2), round(one_rm * high_pct, 2))
