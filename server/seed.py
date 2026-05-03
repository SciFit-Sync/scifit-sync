"""
Reference data seed script — equipment, muscle groups, exercises + mappings.
Run from server/ directory:  python seed.py
Idempotent — skips records that already exist.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models import (
    Equipment,
    EquipmentBrand,
    EquipmentType,
    Exercise,
    ExerciseEquipmentMap,
    ExerciseMuscle,
    MuscleGroup,
    MuscleInvolvement,
)

# ── 원시 데이터 ───────────────────────────────────────────────────────────────

BRANDS = [
    "Technogym",
    "Life Fitness",
    "Hammer Strength",
    "Precor",
    "Matrix",
    "Eleiko",
    "Rogue Fitness",
    "York Barbell",
]

# (name_ko, name_en, body_region)  — name=영어, name_ko=한국어
MUSCLE_GROUPS = [
    ("가슴",       "Chest",         "upper"),
    ("광배근",     "Lats",          "upper"),
    ("상부 등",    "Upper Back",    "upper"),
    ("승모근",     "Trapezius",     "upper"),
    ("어깨 전면",  "Front Deltoid", "upper"),
    ("어깨 측면",  "Side Deltoid",  "upper"),
    ("어깨 후면",  "Rear Deltoid",  "upper"),
    ("이두근",     "Biceps",        "upper"),
    ("삼두근",     "Triceps",       "upper"),
    ("전완근",     "Forearms",      "upper"),
    ("복근",       "Abs",           "core"),
    ("대퇴사두근", "Quadriceps",    "lower"),
    ("햄스트링",   "Hamstrings",    "lower"),
    ("둔근",       "Glutes",        "lower"),
    ("종아리",     "Calves",        "lower"),
]

# (name, name_en, equipment_type, bar_weight_kg, pulley_ratio, has_weight_assist, max_stack_kg, stack_weight_kg)
EQUIPMENTS = [
    ("올림픽 바벨",         "Olympic Barbell",          EquipmentType.BARBELL,    20.0, 1.0, False, None,  None),
    ("EZ 바",               "EZ Bar",                   EquipmentType.BARBELL,    10.0, 1.0, False, None,  None),
    ("덤벨",                "Dumbbell",                  EquipmentType.DUMBBELL,   None, 1.0, False, None,  None),
    ("케이블 크로스오버",   "Cable Crossover",           EquipmentType.CABLE,      None, 1.0, False, 100.0, 2.5),
    ("랫 풀다운 머신",      "Lat Pulldown Machine",      EquipmentType.CABLE,      None, 1.0, False, 100.0, 5.0),
    ("시티드 로우 머신",    "Seated Cable Row Machine",  EquipmentType.CABLE,      None, 1.0, False, 100.0, 5.0),
    ("케이블 머신",         "Cable Machine",             EquipmentType.CABLE,      None, 1.0, False, 100.0, 2.5),
    ("레그 프레스 머신",    "Leg Press Machine",         EquipmentType.MACHINE,    None, 1.0, False, 300.0, 10.0),
    ("레그 익스텐션 머신",  "Leg Extension Machine",     EquipmentType.MACHINE,    None, 1.0, False, 100.0, 5.0),
    ("레그 컬 머신",        "Leg Curl Machine",          EquipmentType.MACHINE,    None, 1.0, False, 100.0, 5.0),
    ("체스트 프레스 머신",  "Chest Press Machine",       EquipmentType.MACHINE,    None, 1.0, False, 100.0, 5.0),
    ("숄더 프레스 머신",    "Shoulder Press Machine",    EquipmentType.MACHINE,    None, 1.0, False, 100.0, 5.0),
    ("스미스 머신",         "Smith Machine",             EquipmentType.MACHINE,    10.0, 1.0, False, None,  None),
    ("카프 레이즈 머신",    "Calf Raise Machine",        EquipmentType.MACHINE,    None, 1.0, False, 150.0, 5.0),
    ("힙 쓰러스트 머신",    "Hip Thrust Machine",        EquipmentType.MACHINE,    None, 1.0, False, 150.0, 5.0),
    ("펙 덱 머신",          "Pec Deck Machine",          EquipmentType.MACHINE,    None, 1.0, False, 80.0,  5.0),
    ("풀업바",              "Pull-up Bar",               EquipmentType.BODYWEIGHT, None, 1.0, False, None,  None),
    ("딥스바",              "Dip Bar",                   EquipmentType.BODYWEIGHT, None, 1.0, False, None,  None),
    ("어시스티드 풀업 머신","Assisted Pull-up Machine",  EquipmentType.BODYWEIGHT, None, 1.0, True,  100.0, 5.0),
]

P  = MuscleInvolvement.PRIMARY
S  = MuscleInvolvement.SECONDARY
ST = MuscleInvolvement.STABILIZER

# muscles: [(근육명(한국어), involvement), ...]
# equipment: [기구명, ...]  — 빈 리스트 = 맨몸 운동
EXERCISES = [
    # ── 가슴 ─────────────────────────────────────────────────────────────────
    {
        "name": "벤치 프레스", "name_en": "Bench Press", "category": "chest",
        "muscles": [("가슴", P), ("삼두근", S), ("어깨 전면", S)],
        "equipment": ["올림픽 바벨", "스미스 머신"],
    },
    {
        "name": "인클라인 벤치 프레스", "name_en": "Incline Bench Press", "category": "chest",
        "muscles": [("가슴", P), ("어깨 전면", S), ("삼두근", S)],
        "equipment": ["올림픽 바벨", "덤벨", "스미스 머신"],
    },
    {
        "name": "디클라인 벤치 프레스", "name_en": "Decline Bench Press", "category": "chest",
        "muscles": [("가슴", P), ("삼두근", S)],
        "equipment": ["올림픽 바벨", "스미스 머신"],
    },
    {
        "name": "덤벨 플라이", "name_en": "Dumbbell Fly", "category": "chest",
        "muscles": [("가슴", P), ("어깨 전면", S)],
        "equipment": ["덤벨"],
    },
    {
        "name": "케이블 플라이", "name_en": "Cable Fly", "category": "chest",
        "muscles": [("가슴", P), ("어깨 전면", S)],
        "equipment": ["케이블 크로스오버"],
    },
    {
        "name": "체스트 프레스 머신", "name_en": "Chest Press Machine", "category": "chest",
        "muscles": [("가슴", P), ("삼두근", S), ("어깨 전면", S)],
        "equipment": ["체스트 프레스 머신"],
    },
    {
        "name": "딥스", "name_en": "Dips", "category": "chest",
        "muscles": [("가슴", P), ("삼두근", S), ("어깨 전면", S)],
        "equipment": ["딥스바", "어시스티드 풀업 머신"],
    },
    {
        "name": "펙 덱 플라이", "name_en": "Pec Deck Fly", "category": "chest",
        "muscles": [("가슴", P), ("어깨 전면", S)],
        "equipment": ["펙 덱 머신"],
    },
    # ── 등 ───────────────────────────────────────────────────────────────────
    {
        "name": "데드리프트", "name_en": "Deadlift", "category": "back",
        "muscles": [("햄스트링", P), ("둔근", P), ("광배근", S), ("승모근", S), ("대퇴사두근", S), ("전완근", ST)],
        "equipment": ["올림픽 바벨"],
    },
    {
        "name": "바벨 로우", "name_en": "Barbell Row", "category": "back",
        "muscles": [("광배근", P), ("상부 등", P), ("이두근", S), ("승모근", S)],
        "equipment": ["올림픽 바벨"],
    },
    {
        "name": "랫 풀다운", "name_en": "Lat Pulldown", "category": "back",
        "muscles": [("광배근", P), ("이두근", S), ("상부 등", S)],
        "equipment": ["랫 풀다운 머신"],
    },
    {
        "name": "시티드 케이블 로우", "name_en": "Seated Cable Row", "category": "back",
        "muscles": [("광배근", P), ("상부 등", P), ("이두근", S)],
        "equipment": ["시티드 로우 머신"],
    },
    {
        "name": "원암 덤벨 로우", "name_en": "One-Arm Dumbbell Row", "category": "back",
        "muscles": [("광배근", P), ("상부 등", S), ("이두근", S)],
        "equipment": ["덤벨"],
    },
    {
        "name": "풀업", "name_en": "Pull-up", "category": "back",
        "muscles": [("광배근", P), ("이두근", S), ("상부 등", S)],
        "equipment": ["풀업바", "어시스티드 풀업 머신"],
    },
    {
        "name": "친업", "name_en": "Chin-up", "category": "back",
        "muscles": [("광배근", P), ("이두근", P), ("상부 등", S)],
        "equipment": ["풀업바", "어시스티드 풀업 머신"],
    },
    {
        "name": "루마니안 데드리프트", "name_en": "Romanian Deadlift", "category": "back",
        "muscles": [("햄스트링", P), ("둔근", P), ("광배근", S)],
        "equipment": ["올림픽 바벨", "덤벨"],
    },
    {
        "name": "스모 데드리프트", "name_en": "Sumo Deadlift", "category": "back",
        "muscles": [("둔근", P), ("햄스트링", P), ("대퇴사두근", S), ("광배근", S)],
        "equipment": ["올림픽 바벨"],
    },
    # ── 어깨 ─────────────────────────────────────────────────────────────────
    {
        "name": "오버헤드 프레스", "name_en": "Overhead Press", "category": "shoulder",
        "muscles": [("어깨 전면", P), ("어깨 측면", S), ("삼두근", S), ("승모근", ST)],
        "equipment": ["올림픽 바벨", "스미스 머신"],
    },
    {
        "name": "덤벨 숄더 프레스", "name_en": "Dumbbell Shoulder Press", "category": "shoulder",
        "muscles": [("어깨 전면", P), ("어깨 측면", S), ("삼두근", S)],
        "equipment": ["덤벨", "숄더 프레스 머신"],
    },
    {
        "name": "사이드 레터럴 레이즈", "name_en": "Side Lateral Raise", "category": "shoulder",
        "muscles": [("어깨 측면", P), ("승모근", S)],
        "equipment": ["덤벨", "케이블 머신"],
    },
    {
        "name": "프론트 레이즈", "name_en": "Front Raise", "category": "shoulder",
        "muscles": [("어깨 전면", P), ("어깨 측면", S)],
        "equipment": ["덤벨", "올림픽 바벨", "케이블 머신"],
    },
    {
        "name": "페이스 풀", "name_en": "Face Pull", "category": "shoulder",
        "muscles": [("어깨 후면", P), ("상부 등", S), ("승모근", S)],
        "equipment": ["케이블 머신"],
    },
    {
        "name": "리어 델트 플라이", "name_en": "Rear Delt Fly", "category": "shoulder",
        "muscles": [("어깨 후면", P), ("상부 등", S)],
        "equipment": ["덤벨", "케이블 크로스오버"],
    },
    # ── 이두근 ───────────────────────────────────────────────────────────────
    {
        "name": "바벨 컬", "name_en": "Barbell Curl", "category": "biceps",
        "muscles": [("이두근", P), ("전완근", S)],
        "equipment": ["올림픽 바벨", "EZ 바"],
    },
    {
        "name": "덤벨 컬", "name_en": "Dumbbell Curl", "category": "biceps",
        "muscles": [("이두근", P), ("전완근", S)],
        "equipment": ["덤벨"],
    },
    {
        "name": "해머 컬", "name_en": "Hammer Curl", "category": "biceps",
        "muscles": [("이두근", P), ("전완근", P)],
        "equipment": ["덤벨"],
    },
    {
        "name": "케이블 컬", "name_en": "Cable Curl", "category": "biceps",
        "muscles": [("이두근", P), ("전완근", S)],
        "equipment": ["케이블 머신"],
    },
    {
        "name": "인클라인 덤벨 컬", "name_en": "Incline Dumbbell Curl", "category": "biceps",
        "muscles": [("이두근", P)],
        "equipment": ["덤벨"],
    },
    # ── 삼두근 ───────────────────────────────────────────────────────────────
    {
        "name": "트라이셉스 푸시다운", "name_en": "Tricep Pushdown", "category": "triceps",
        "muscles": [("삼두근", P)],
        "equipment": ["케이블 머신"],
    },
    {
        "name": "스컬 크러셔", "name_en": "Skull Crusher", "category": "triceps",
        "muscles": [("삼두근", P)],
        "equipment": ["올림픽 바벨", "EZ 바", "덤벨"],
    },
    {
        "name": "오버헤드 트라이셉스 익스텐션", "name_en": "Overhead Tricep Extension", "category": "triceps",
        "muscles": [("삼두근", P)],
        "equipment": ["덤벨", "케이블 머신"],
    },
    {
        "name": "트라이셉스 딥스", "name_en": "Tricep Dips", "category": "triceps",
        "muscles": [("삼두근", P), ("가슴", S)],
        "equipment": ["딥스바", "어시스티드 풀업 머신"],
    },
    {
        "name": "클로즈 그립 벤치 프레스", "name_en": "Close-Grip Bench Press", "category": "triceps",
        "muscles": [("삼두근", P), ("가슴", S), ("어깨 전면", S)],
        "equipment": ["올림픽 바벨"],
    },
    # ── 하체 ─────────────────────────────────────────────────────────────────
    {
        "name": "스쿼트", "name_en": "Squat", "category": "legs",
        "muscles": [("대퇴사두근", P), ("둔근", P), ("햄스트링", S), ("복근", ST)],
        "equipment": ["올림픽 바벨", "스미스 머신"],
    },
    {
        "name": "프론트 스쿼트", "name_en": "Front Squat", "category": "legs",
        "muscles": [("대퇴사두근", P), ("둔근", S), ("복근", ST)],
        "equipment": ["올림픽 바벨", "스미스 머신"],
    },
    {
        "name": "레그 프레스", "name_en": "Leg Press", "category": "legs",
        "muscles": [("대퇴사두근", P), ("둔근", S), ("햄스트링", S)],
        "equipment": ["레그 프레스 머신"],
    },
    {
        "name": "레그 익스텐션", "name_en": "Leg Extension", "category": "legs",
        "muscles": [("대퇴사두근", P)],
        "equipment": ["레그 익스텐션 머신"],
    },
    {
        "name": "레그 컬", "name_en": "Leg Curl", "category": "legs",
        "muscles": [("햄스트링", P)],
        "equipment": ["레그 컬 머신"],
    },
    {
        "name": "런지", "name_en": "Lunge", "category": "legs",
        "muscles": [("대퇴사두근", P), ("둔근", P), ("햄스트링", S)],
        "equipment": ["올림픽 바벨", "덤벨"],
    },
    {
        "name": "힙 쓰러스트", "name_en": "Hip Thrust", "category": "legs",
        "muscles": [("둔근", P), ("햄스트링", S)],
        "equipment": ["올림픽 바벨", "힙 쓰러스트 머신"],
    },
    {
        "name": "카프 레이즈", "name_en": "Calf Raise", "category": "legs",
        "muscles": [("종아리", P)],
        "equipment": ["카프 레이즈 머신", "올림픽 바벨"],
    },
    {
        "name": "불가리안 스플릿 스쿼트", "name_en": "Bulgarian Split Squat", "category": "legs",
        "muscles": [("대퇴사두근", P), ("둔근", P), ("햄스트링", S)],
        "equipment": ["덤벨", "올림픽 바벨"],
    },
    # ── 코어 ─────────────────────────────────────────────────────────────────
    {
        "name": "플랭크", "name_en": "Plank", "category": "core",
        "muscles": [("복근", P)],
        "equipment": [],
    },
    {
        "name": "크런치", "name_en": "Crunch", "category": "core",
        "muscles": [("복근", P)],
        "equipment": [],
    },
    {
        "name": "레그 레이즈", "name_en": "Leg Raise", "category": "core",
        "muscles": [("복근", P)],
        "equipment": [],
    },
    {
        "name": "케이블 크런치", "name_en": "Cable Crunch", "category": "core",
        "muscles": [("복근", P)],
        "equipment": ["케이블 머신"],
    },
    {
        "name": "AB 롤아웃", "name_en": "Ab Rollout", "category": "core",
        "muscles": [("복근", P)],
        "equipment": [],
    },
]


# ── seeding 함수 ──────────────────────────────────────────────────────────────

async def seed() -> None:
    async with async_session_factory() as session:

        # 1. Equipment brands
        print("▶ equipment_brands 삽입 중...")
        brand_map: dict[str, object] = {}
        for name in BRANDS:
            row = (await session.execute(select(EquipmentBrand).where(EquipmentBrand.name == name))).scalar_one_or_none()
            if not row:
                row = EquipmentBrand(name=name)
                session.add(row)
                await session.flush()
            brand_map[name] = row.id
        print(f"  완료 ({len(brand_map)}개)")

        # 2. Muscle groups — name=영어, name_ko=한국어
        print("▶ muscle_groups 삽입 중...")
        muscle_map: dict[str, object] = {}  # 한국어명 → id
        for name_ko, name_en, body_region in MUSCLE_GROUPS:
            row = (await session.execute(select(MuscleGroup).where(MuscleGroup.name_ko == name_ko))).scalar_one_or_none()
            if not row:
                row = MuscleGroup(name=name_en, name_ko=name_ko, body_region=body_region)
                session.add(row)
                await session.flush()
            muscle_map[name_ko] = row.id
        print(f"  완료 ({len(muscle_map)}개)")

        # 3. Equipment
        print("▶ equipments 삽입 중...")
        eq_map: dict[str, object] = {}
        for (name, name_en, equipment_type, bar_weight_kg, pulley_ratio,
             has_weight_assist, max_stack_kg, stack_weight_kg) in EQUIPMENTS:
            row = (await session.execute(select(Equipment).where(Equipment.name == name))).scalar_one_or_none()
            if not row:
                row = Equipment(
                    name=name,
                    name_en=name_en,
                    equipment_type=equipment_type,
                    bar_weight_kg=bar_weight_kg,
                    pulley_ratio=pulley_ratio,
                    has_weight_assist=has_weight_assist,
                    max_stack_kg=max_stack_kg,
                    stack_weight_kg=stack_weight_kg,
                )
                session.add(row)
                await session.flush()
            eq_map[name] = row.id
        print(f"  완료 ({len(eq_map)}개)")

        # 4. Exercises + mappings
        print("▶ exercises + 매핑 삽입 중...")
        ex_count = 0
        for ex_data in EXERCISES:
            row = (await session.execute(select(Exercise).where(Exercise.name == ex_data["name"]))).scalar_one_or_none()
            if not row:
                row = Exercise(name=ex_data["name"], name_en=ex_data["name_en"], category=ex_data["category"])
                session.add(row)
                await session.flush()
                ex_count += 1
            ex_id = row.id

            # exercise_muscles
            for muscle_ko, involvement in ex_data["muscles"]:
                mg_id = muscle_map[muscle_ko]
                exists = (await session.execute(
                    select(ExerciseMuscle).where(
                        ExerciseMuscle.exercise_id == ex_id,
                        ExerciseMuscle.muscle_group_id == mg_id,
                    )
                )).scalar_one_or_none()
                if not exists:
                    session.add(ExerciseMuscle(exercise_id=ex_id, muscle_group_id=mg_id, involvement=involvement))

            # exercise_equipment_map
            for eq_name in ex_data["equipment"]:
                eq_id = eq_map[eq_name]
                exists = (await session.execute(
                    select(ExerciseEquipmentMap).where(
                        ExerciseEquipmentMap.exercise_id == ex_id,
                        ExerciseEquipmentMap.equipment_id == eq_id,
                    )
                )).scalar_one_or_none()
                if not exists:
                    session.add(ExerciseEquipmentMap(exercise_id=ex_id, equipment_id=eq_id))

        print(f"  완료 (신규 {ex_count}개 / 전체 {len(EXERCISES)}개)")

        await session.commit()
        print("\n✅ 시드 데이터 삽입 완료!")


if __name__ == "__main__":
    asyncio.run(seed())
