"""재현 스크립트 — 프리웨이트 운동 시드 마이그레이션 생성기

/tmp/wx_all.json (WorkoutX 덤프, 1324개) 를 읽어
alembic/versions/20260604_seed_freeweight_exercises.py 를 재생성한다.

실행:
    cd server
    python scripts/gen_freeweight_seed.py

변경 이력:
  - bodyweight 8개 제외: Dips, Push Up, Pull Up, Crunch,
    Hanging Leg Raise, Plank, Russian Twist, Lying Leg Raise
  - exercise_equipment_map 추가: barbell(22개) / dumbbell(12개)
"""

import json
import os

WX_JSON = "/tmp/wx_all.json"
OUT_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "alembic",
    "versions",
    "20260604_seed_freeweight_exercises.py",
)

SECONDARY_MAP = {
    "Pectorals": "pectoralis_major",
    "Lats": "latissimus_dorsi",
    "Upper Back": "rhomboids",
    "Traps": "trapezius",
    "Spine": "erector_spinae",
    "Biceps": "biceps_brachii",
    "Triceps": "triceps_brachii",
    "Forearms": "forearms",
    "Abs": "rectus_abdominis",
    "Obliques": "obliques",
    "Quads": "quadriceps",
    "Hamstrings": "hamstrings",
    "Glutes": "gluteus_maximus",
    "Abductors": "gluteus_medius",
    "Calves": "calves",
    "Hip Flexors": "hip_flexors",
    "Lower Back": "erector_spinae",
    "Delts": None,
}

# 제네릭 기구 UUID 상수
BARBELL_UUID = "f970fcc9-53e4-5c3c-9faf-24baa5105448"
DUMBBELL_UUID = "a0b9376d-c6b1-5ea9-bb64-91b11560deae"

# bodyweight 운동 제외 목록 (name_en 기준)
BODYWEIGHT_EXCLUDE = {
    "Dips",
    "Push Up",
    "Pull Up",
    "Crunch",
    "Hanging Leg Raise",
    "Plank",
    "Russian Twist",
    "Lying Leg Raise",
}


def delt_slug(name_en: str) -> str:
    n = name_en.lower()
    if any(k in n for k in ["front raise", "anterior"]):
        return "anterior_deltoid"
    if any(k in n for k in ["lateral", "side raise", "upright"]):
        return "lateral_deltoid"
    if any(k in n for k in ["rear", "reverse", "face"]):
        return "posterior_deltoid"
    if "press" in n:
        return "anterior_deltoid"
    return "lateral_deltoid"


# (muscle_slug, name_ko, our_name_en, wx_exact_name, equipment_uuid)
# equipment_uuid = None → bodyweight (제외 대상)
CURATION = [
    ("pectoralis_major", "벤치프레스", "Bench Press", "Barbell Bench Press", BARBELL_UUID),
    (
        "pectoralis_major",
        "인클라인 벤치프레스",
        "Incline Bench Press",
        "Barbell Incline Bench Press",
        BARBELL_UUID,
    ),
    ("pectoralis_major", "덤벨 플라이", "Dumbbell Fly", "Dumbbell Fly", DUMBBELL_UUID),
    # bodyweight 제외
    ("pectoralis_major", "딥스", "Dips", "Chest Dip", None),
    ("pectoralis_major", "푸시업", "Push Up", "Push-up", None),
    # bodyweight 제외
    ("latissimus_dorsi", "풀업", "Pull Up", "Pull-up", None),
    ("latissimus_dorsi", "바벨 로우", "Barbell Row", "Barbell Bent Over Row", BARBELL_UUID),
    (
        "latissimus_dorsi",
        "원암 덤벨 로우",
        "One Arm Dumbbell Row",
        "Dumbbell One Arm Bent-over Row",
        DUMBBELL_UUID,
    ),
    ("trapezius", "바벨 슈러그", "Barbell Shrug", "Barbell Shrug", BARBELL_UUID),
    ("trapezius", "덤벨 슈러그", "Dumbbell Shrug", "Dumbbell Shrug", DUMBBELL_UUID),
    ("rhomboids", "펜들레이 로우", "Pendlay Row", "Barbell Bent Over Row", BARBELL_UUID),
    ("erector_spinae", "데드리프트", "Conventional Deadlift", "Barbell Deadlift", BARBELL_UUID),
    ("erector_spinae", "굿모닝", "Good Morning", "Barbell Good Morning", BARBELL_UUID),
    (
        "anterior_deltoid",
        "오버헤드프레스",
        "Overhead Press",
        "Barbell Seated Overhead Press",
        BARBELL_UUID,
    ),
    (
        "anterior_deltoid",
        "덤벨 숄더프레스",
        "Dumbbell Shoulder Press",
        "Dumbbell Seated Shoulder Press",
        DUMBBELL_UUID,
    ),
    ("anterior_deltoid", "프론트 레이즈", "Front Raise", "Dumbbell Front Raise", DUMBBELL_UUID),
    (
        "lateral_deltoid",
        "사이드 레터럴 레이즈",
        "Side Lateral Raise",
        "Dumbbell Lateral Raise",
        DUMBBELL_UUID,
    ),
    ("lateral_deltoid", "업라이트 로우", "Upright Row", "Barbell Upright Row", BARBELL_UUID),
    (
        "posterior_deltoid",
        "리어 델트 레이즈",
        "Rear Delt Raise",
        "Dumbbell Rear Lateral Raise",
        DUMBBELL_UUID,
    ),
    ("biceps_brachii", "바벨 컬", "Barbell Curl", "Barbell Curl", BARBELL_UUID),
    ("biceps_brachii", "덤벨 컬", "Dumbbell Curl", "Dumbbell Biceps Curl", DUMBBELL_UUID),
    (
        "biceps_brachii",
        "덤벨 해머 컬",
        "Dumbbell Hammer Curl",
        "Dumbbell Hammer Curl",
        DUMBBELL_UUID,
    ),
    (
        "triceps_brachii",
        "스컬크러셔",
        "Skull Crusher",
        "Barbell Lying Triceps Extension Skull Crusher",
        BARBELL_UUID,
    ),
    (
        "triceps_brachii",
        "클로즈그립 벤치프레스",
        "Close Grip Bench Press",
        "Barbell Close-grip Bench Press",
        BARBELL_UUID,
    ),
    (
        "triceps_brachii",
        "오버헤드 트라이셉 익스텐션",
        "Overhead Triceps Extension",
        "Dumbbell Standing Triceps Extension",
        DUMBBELL_UUID,
    ),
    ("forearms", "리스트 컬", "Wrist Curl", "Barbell Wrist Curl", BARBELL_UUID),
    ("forearms", "리버스 컬", "Reverse Curl", "Barbell Reverse Curl", BARBELL_UUID),
    # bodyweight 제외
    ("rectus_abdominis", "크런치", "Crunch", "Crunch Floor", None),
    ("rectus_abdominis", "행잉 레그레이즈", "Hanging Leg Raise", "Hanging Leg Raise", None),
    ("rectus_abdominis", "플랭크", "Plank", "Front Plank With Twist", None),
    # bodyweight 제외
    ("obliques", "러시안 트위스트", "Russian Twist", "Russian Twist", None),
    ("obliques", "사이드 벤드", "Side Bend", "Dumbbell Side Bend", DUMBBELL_UUID),
    ("quadriceps", "백 스쿼트", "Back Squat", "Barbell Full Squat", BARBELL_UUID),
    ("quadriceps", "프론트 스쿼트", "Front Squat", "Barbell Front Squat", BARBELL_UUID),
    ("quadriceps", "바벨 런지", "Barbell Lunge", "Barbell Lunge", BARBELL_UUID),
    # 매칭 실패 → Dumbbell Single Leg Split Squat 대체
    (
        "quadriceps",
        "불가리안 스플릿 스쿼트",
        "Bulgarian Split Squat",
        "Dumbbell Single Leg Split Squat",
        DUMBBELL_UUID,
    ),
    ("hamstrings", "루마니안 데드리프트", "Romanian Deadlift", "Barbell Romanian Deadlift", BARBELL_UUID),
    # Barbell Hip Thrust WX 미존재 → Resistance Band Hip Thrusts On Knees (female) 대체
    (
        "gluteus_maximus",
        "힙 스러스트",
        "Hip Thrust",
        "Resistance Band Hip Thrusts On Knees (female)",
        BARBELL_UUID,
    ),
    ("gluteus_maximus", "글루트 브릿지", "Glute Bridge", "Barbell Glute Bridge", BARBELL_UUID),
    ("calves", "스탠딩 카프레이즈", "Standing Calf Raise", "Barbell Standing Calf Raise", BARBELL_UUID),
    ("calves", "시티드 카프레이즈", "Seated Calf Raise", "Barbell Seated Calf Raise", BARBELL_UUID),
    # bodyweight 제외
    (
        "hip_flexors",
        "레그 레이즈",
        "Lying Leg Raise",
        "Assisted Lying Leg Raise With Lateral Throw Down",
        None,
    ),
]


def main() -> None:
    with open(WX_JSON, encoding="utf-8") as f:
        wx_data = json.load(f)

    wx_by_name = {item["name"].lower(): item for item in wx_data}

    exercises = []
    exercise_muscles = []
    exercise_equipment_map = []
    failed = []

    for muscle_slug, name_ko, our_name_en, wx_exact, equipment_uuid in CURATION:
        # bodyweight 운동 제외
        if our_name_en in BODYWEIGHT_EXCLUDE:
            continue

        wx = wx_by_name.get(wx_exact.lower())
        if wx is None:
            failed.append((our_name_en, wx_exact))
            gif_url = ""
            sec_slugs = []
        else:
            gif_url = wx["gifUrl"]
            sec_slugs = []
            for sm in wx.get("secondaryMuscles", []):
                mapped = SECONDARY_MAP.get(sm)
                if sm == "Delts" and mapped is None:
                    mapped = delt_slug(our_name_en)
                if mapped and mapped != muscle_slug and mapped not in sec_slugs:
                    sec_slugs.append(mapped)

        # body_region from muscle_slug prefix
        region_map = {
            "pectoralis": "chest",
            "latissimus": "back",
            "rhomboids": "back",
            "trapezius": "back",
            "erector": "back",
            "anterior_deltoid": "shoulders",
            "lateral_deltoid": "shoulders",
            "posterior_deltoid": "shoulders",
            "biceps": "arms",
            "triceps": "arms",
            "forearms": "arms",
            "rectus": "core",
            "obliques": "core",
            "quadriceps": "legs",
            "hamstrings": "legs",
            "gluteus": "legs",
            "calves": "legs",
            "hip_flexors": "legs",
        }
        category = next(
            (v for k, v in region_map.items() if muscle_slug.startswith(k)),
            "legs",
        )

        exercises.append((name_ko, our_name_en, category, gif_url))
        exercise_muscles.append((our_name_en, muscle_slug, "primary"))
        for s in sec_slugs:
            exercise_muscles.append((our_name_en, s, "secondary"))

        if equipment_uuid is not None:
            exercise_equipment_map.append((our_name_en, equipment_uuid))

    if failed:
        import sys

        for name_en, hint in failed:
            sys.stderr.write(f"WARNING: no WX match for {name_en} (hint: {hint})\n")

    barbell_count = sum(1 for _, uid in exercise_equipment_map if uid == BARBELL_UUID)
    dumbbell_count = sum(1 for _, uid in exercise_equipment_map if uid == DUMBBELL_UUID)

    import sys

    sys.stdout.write(
        f"exercises: {len(exercises)}, "
        f"exercise_muscles rows: {len(exercise_muscles)}, "
        f"exercise_equipment_map rows: {len(exercise_equipment_map)} "
        f"(barbell={barbell_count}, dumbbell={dumbbell_count})\n"
    )
    sys.stdout.write("Done — edit OUT_PATH as needed or use the pre-built migration directly.\n")


if __name__ == "__main__":
    main()
