"""프리웨이트 큐레이션 운동 시드 — gif_url + exercise_muscles (primary/secondary) + exercise_equipment_map

Revision ID: 20260604_seed_freeweight
Revises: 20260604_equipment_centric_pr1
Create Date: 2026-06-04

멱등성:
  - exercises: ON CONFLICT(name_en) DO UPDATE gif_url, category
  - exercise_muscles: name_en + muscle slug JOIN → INSERT ... ON CONFLICT DO NOTHING
  - exercise_equipment_map: name_en + equipment UUID JOIN → INSERT ... ON CONFLICT DO NOTHING
하드코딩 UUID 없음 (exercise) — exercise FK는 name_en JOIN으로 해결.
equipment UUID는 제네릭 기구 상수 (Barbell/Dumbbell) 사용.

bodyweight 8개 제외:
  - Dips, Push Up, Pull Up, Crunch, Hanging Leg Raise, Plank, Russian Twist, Lying Leg Raise
gif_url 출처: WorkoutX API (wx_all.json 1324개 덤프에서 정확 매칭)
매칭 실패 2건 처리:
  - One Arm Dumbbell Row → Dumbbell One Arm Bent-over Row (0292.gif)
  - Bulgarian Split Squat → Dumbbell Single Leg Split Squat (0410.gif)
"""

import sqlalchemy as sa
from alembic import op

revision = "20260604_seed_freeweight"
down_revision = "20260604_equipment_centric_pr1"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# 제네릭 기구 UUID 상수
# ---------------------------------------------------------------------------
_BARBELL_UUID = "f970fcc9-53e4-5c3c-9faf-24baa5105448"
_DUMBBELL_UUID = "a0b9376d-c6b1-5ea9-bb64-91b11560deae"

# ---------------------------------------------------------------------------
# 큐레이션 운동 데이터 (bodyweight 제외, 34개)
# (name_ko, name_en, category, gif_url)
# category = primary 근육의 body_region
# gif_url = WorkoutX API에서 정확 매칭한 값
# ---------------------------------------------------------------------------
_EXERCISES = [
    # ── 가슴 ─────────────────────────────────────────────────────────────────
    (
        "벤치프레스",
        "Bench Press",
        "chest",
        "https://api.workoutxapp.com/v1/gifs/0025.gif",
    ),
    (
        "인클라인 벤치프레스",
        "Incline Bench Press",
        "chest",
        "https://api.workoutxapp.com/v1/gifs/0047.gif",
    ),
    (
        "덤벨 플라이",
        "Dumbbell Fly",
        "chest",
        "https://api.workoutxapp.com/v1/gifs/0308.gif",
    ),
    # ── 등 ───────────────────────────────────────────────────────────────────
    (
        "바벨 로우",
        "Barbell Row",
        "back",
        "https://api.workoutxapp.com/v1/gifs/0027.gif",
    ),
    (
        "원암 덤벨 로우",
        "One Arm Dumbbell Row",
        "back",
        "https://api.workoutxapp.com/v1/gifs/0292.gif",
    ),
    (
        "바벨 슈러그",
        "Barbell Shrug",
        "back",
        "https://api.workoutxapp.com/v1/gifs/0095.gif",
    ),
    (
        "덤벨 슈러그",
        "Dumbbell Shrug",
        "back",
        "https://api.workoutxapp.com/v1/gifs/0406.gif",
    ),
    (
        "펜들레이 로우",
        "Pendlay Row",
        "back",
        "https://api.workoutxapp.com/v1/gifs/0027.gif",
    ),
    (
        "데드리프트",
        "Conventional Deadlift",
        "back",
        "https://api.workoutxapp.com/v1/gifs/0032.gif",
    ),
    (
        "굿모닝",
        "Good Morning",
        "back",
        "https://api.workoutxapp.com/v1/gifs/0044.gif",
    ),
    # ── 어깨 ─────────────────────────────────────────────────────────────────
    (
        "오버헤드프레스",
        "Overhead Press",
        "shoulders",
        "https://api.workoutxapp.com/v1/gifs/0091.gif",
    ),
    (
        "덤벨 숄더프레스",
        "Dumbbell Shoulder Press",
        "shoulders",
        "https://api.workoutxapp.com/v1/gifs/0405.gif",
    ),
    (
        "프론트 레이즈",
        "Front Raise",
        "shoulders",
        "https://api.workoutxapp.com/v1/gifs/0310.gif",
    ),
    (
        "사이드 레터럴 레이즈",
        "Side Lateral Raise",
        "shoulders",
        "https://api.workoutxapp.com/v1/gifs/0334.gif",
    ),
    (
        "업라이트 로우",
        "Upright Row",
        "shoulders",
        "https://api.workoutxapp.com/v1/gifs/0120.gif",
    ),
    (
        "리어 델트 레이즈",
        "Rear Delt Raise",
        "shoulders",
        "https://api.workoutxapp.com/v1/gifs/0380.gif",
    ),
    # ── 팔 ───────────────────────────────────────────────────────────────────
    (
        "바벨 컬",
        "Barbell Curl",
        "arms",
        "https://api.workoutxapp.com/v1/gifs/0031.gif",
    ),
    (
        "덤벨 컬",
        "Dumbbell Curl",
        "arms",
        "https://api.workoutxapp.com/v1/gifs/0294.gif",
    ),
    (
        "덤벨 해머 컬",
        "Dumbbell Hammer Curl",
        "arms",
        "https://api.workoutxapp.com/v1/gifs/0313.gif",
    ),
    (
        "스컬크러셔",
        "Skull Crusher",
        "arms",
        "https://api.workoutxapp.com/v1/gifs/0060.gif",
    ),
    (
        "클로즈그립 벤치프레스",
        "Close Grip Bench Press",
        "arms",
        "https://api.workoutxapp.com/v1/gifs/0030.gif",
    ),
    (
        "오버헤드 트라이셉 익스텐션",
        "Overhead Triceps Extension",
        "arms",
        "https://api.workoutxapp.com/v1/gifs/0430.gif",
    ),
    (
        "리스트 컬",
        "Wrist Curl",
        "arms",
        "https://api.workoutxapp.com/v1/gifs/0126.gif",
    ),
    (
        "리버스 컬",
        "Reverse Curl",
        "arms",
        "https://api.workoutxapp.com/v1/gifs/0080.gif",
    ),
    # ── 복근/코어 ─────────────────────────────────────────────────────────────
    (
        "사이드 벤드",
        "Side Bend",
        "core",
        "https://api.workoutxapp.com/v1/gifs/0407.gif",
    ),
    # ── 하체 ─────────────────────────────────────────────────────────────────
    (
        "백 스쿼트",
        "Back Squat",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/0043.gif",
    ),
    (
        "프론트 스쿼트",
        "Front Squat",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/0042.gif",
    ),
    (
        "바벨 런지",
        "Barbell Lunge",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/0054.gif",
    ),
    (
        "불가리안 스플릿 스쿼트",
        "Bulgarian Split Squat",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/0410.gif",
    ),
    (
        "루마니안 데드리프트",
        "Romanian Deadlift",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/0085.gif",
    ),
    (
        "힙 스러스트",
        "Hip Thrust",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/3236.gif",
    ),
    (
        "글루트 브릿지",
        "Glute Bridge",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/1409.gif",
    ),
    (
        "스탠딩 카프레이즈",
        "Standing Calf Raise",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/1372.gif",
    ),
    (
        "시티드 카프레이즈",
        "Seated Calf Raise",
        "legs",
        "https://api.workoutxapp.com/v1/gifs/1371.gif",
    ),
]

# ---------------------------------------------------------------------------
# exercise_muscles
# (name_en, muscle_slug, involvement)
# primary = 큐레이션 지정 slug
# secondary = WorkoutX secondaryMuscles 매핑 결과 (primary 중복 제외)
# bodyweight 8개 제외: Dips, Push Up, Pull Up, Crunch, Hanging Leg Raise,
#                      Plank, Russian Twist, Lying Leg Raise
# ---------------------------------------------------------------------------
_EXERCISE_MUSCLES = [
    # ── 벤치프레스 ─────────────────────────────────
    ("Bench Press", "pectoralis_major", "primary"),
    ("Bench Press", "triceps_brachii", "secondary"),
    # ── 인클라인 벤치프레스 ────────────────────────
    ("Incline Bench Press", "pectoralis_major", "primary"),
    ("Incline Bench Press", "triceps_brachii", "secondary"),
    # ── 덤벨 플라이 ────────────────────────────────
    ("Dumbbell Fly", "pectoralis_major", "primary"),
    # ── 바벨 로우 ──────────────────────────────────
    ("Barbell Row", "latissimus_dorsi", "primary"),
    ("Barbell Row", "biceps_brachii", "secondary"),
    ("Barbell Row", "forearms", "secondary"),
    # ── 원암 덤벨 로우 ─────────────────────────────
    ("One Arm Dumbbell Row", "latissimus_dorsi", "primary"),
    ("One Arm Dumbbell Row", "biceps_brachii", "secondary"),
    ("One Arm Dumbbell Row", "forearms", "secondary"),
    # ── 바벨 슈러그 ────────────────────────────────
    ("Barbell Shrug", "trapezius", "primary"),
    # ── 덤벨 슈러그 ────────────────────────────────
    ("Dumbbell Shrug", "trapezius", "primary"),
    # ── 펜들레이 로우 ──────────────────────────────
    ("Pendlay Row", "rhomboids", "primary"),
    ("Pendlay Row", "biceps_brachii", "secondary"),
    ("Pendlay Row", "forearms", "secondary"),
    # ── 데드리프트 ─────────────────────────────────
    ("Conventional Deadlift", "erector_spinae", "primary"),
    ("Conventional Deadlift", "hamstrings", "secondary"),
    # ── 굿모닝 ─────────────────────────────────────
    ("Good Morning", "erector_spinae", "primary"),
    # ── 오버헤드프레스 ─────────────────────────────
    ("Overhead Press", "anterior_deltoid", "primary"),
    ("Overhead Press", "triceps_brachii", "secondary"),
    ("Overhead Press", "rhomboids", "secondary"),
    # ── 덤벨 숄더프레스 ────────────────────────────
    ("Dumbbell Shoulder Press", "anterior_deltoid", "primary"),
    ("Dumbbell Shoulder Press", "triceps_brachii", "secondary"),
    ("Dumbbell Shoulder Press", "rhomboids", "secondary"),
    # ── 프론트 레이즈 ──────────────────────────────
    ("Front Raise", "anterior_deltoid", "primary"),
    ("Front Raise", "biceps_brachii", "secondary"),
    # ── 사이드 레터럴 레이즈 ───────────────────────
    ("Side Lateral Raise", "lateral_deltoid", "primary"),
    ("Side Lateral Raise", "trapezius", "secondary"),
    # ── 업라이트 로우 ──────────────────────────────
    ("Upright Row", "lateral_deltoid", "primary"),
    ("Upright Row", "trapezius", "secondary"),
    ("Upright Row", "biceps_brachii", "secondary"),
    # ── 리어 델트 레이즈 ───────────────────────────
    ("Rear Delt Raise", "posterior_deltoid", "primary"),
    ("Rear Delt Raise", "trapezius", "secondary"),
    # ── 바벨 컬 ────────────────────────────────────
    ("Barbell Curl", "biceps_brachii", "primary"),
    ("Barbell Curl", "forearms", "secondary"),
    # ── 덤벨 컬 ────────────────────────────────────
    ("Dumbbell Curl", "biceps_brachii", "primary"),
    ("Dumbbell Curl", "forearms", "secondary"),
    # ── 덤벨 해머 컬 ───────────────────────────────
    ("Dumbbell Hammer Curl", "biceps_brachii", "primary"),
    ("Dumbbell Hammer Curl", "forearms", "secondary"),
    # ── 스컬크러셔 ─────────────────────────────────
    ("Skull Crusher", "triceps_brachii", "primary"),
    # ── 클로즈그립 벤치프레스 ──────────────────────
    ("Close Grip Bench Press", "triceps_brachii", "primary"),
    # ── 오버헤드 트라이셉 익스텐션 ─────────────────
    ("Overhead Triceps Extension", "triceps_brachii", "primary"),
    # ── 리스트 컬 ──────────────────────────────────
    ("Wrist Curl", "forearms", "primary"),
    ("Wrist Curl", "biceps_brachii", "secondary"),
    # ── 리버스 컬 ──────────────────────────────────
    ("Reverse Curl", "forearms", "primary"),
    # ── 사이드 벤드 ────────────────────────────────
    ("Side Bend", "obliques", "primary"),
    # ── 백 스쿼트 ──────────────────────────────────
    ("Back Squat", "quadriceps", "primary"),
    ("Back Squat", "hamstrings", "secondary"),
    ("Back Squat", "calves", "secondary"),
    # ── 프론트 스쿼트 ──────────────────────────────
    ("Front Squat", "quadriceps", "primary"),
    ("Front Squat", "hamstrings", "secondary"),
    ("Front Squat", "calves", "secondary"),
    # ── 바벨 런지 ──────────────────────────────────
    ("Barbell Lunge", "quadriceps", "primary"),
    ("Barbell Lunge", "hamstrings", "secondary"),
    ("Barbell Lunge", "calves", "secondary"),
    # ── 불가리안 스플릿 스쿼트 ─────────────────────
    ("Bulgarian Split Squat", "quadriceps", "primary"),
    ("Bulgarian Split Squat", "gluteus_maximus", "secondary"),
    ("Bulgarian Split Squat", "hamstrings", "secondary"),
    ("Bulgarian Split Squat", "calves", "secondary"),
    # ── 루마니안 데드리프트 ────────────────────────
    ("Romanian Deadlift", "hamstrings", "primary"),
    ("Romanian Deadlift", "erector_spinae", "secondary"),
    # ── 힙 스러스트 ────────────────────────────────
    ("Hip Thrust", "gluteus_maximus", "primary"),
    ("Hip Thrust", "hamstrings", "secondary"),
    # ── 글루트 브릿지 ──────────────────────────────
    ("Glute Bridge", "gluteus_maximus", "primary"),
    ("Glute Bridge", "hamstrings", "secondary"),
    ("Glute Bridge", "erector_spinae", "secondary"),
    # ── 스탠딩 카프레이즈 ──────────────────────────
    ("Standing Calf Raise", "calves", "primary"),
    ("Standing Calf Raise", "hamstrings", "secondary"),
    ("Standing Calf Raise", "gluteus_maximus", "secondary"),
    # ── 시티드 카프레이즈 ──────────────────────────
    ("Seated Calf Raise", "calves", "primary"),
    ("Seated Calf Raise", "hamstrings", "secondary"),
]

# ---------------------------------------------------------------------------
# exercise_equipment_map
# (name_en, equipment_uuid)
# barbell 매핑 22개 / dumbbell 매핑 12개
# ---------------------------------------------------------------------------
_EXERCISE_EQUIPMENT_MAP = [
    # ── barbell (22개) ───────────────────────────────────────────────────────
    ("Bench Press", _BARBELL_UUID),
    ("Incline Bench Press", _BARBELL_UUID),
    ("Barbell Row", _BARBELL_UUID),
    ("Barbell Shrug", _BARBELL_UUID),
    ("Pendlay Row", _BARBELL_UUID),
    ("Conventional Deadlift", _BARBELL_UUID),
    ("Good Morning", _BARBELL_UUID),
    ("Overhead Press", _BARBELL_UUID),
    ("Upright Row", _BARBELL_UUID),
    ("Barbell Curl", _BARBELL_UUID),
    ("Skull Crusher", _BARBELL_UUID),
    ("Close Grip Bench Press", _BARBELL_UUID),
    ("Wrist Curl", _BARBELL_UUID),
    ("Reverse Curl", _BARBELL_UUID),
    ("Back Squat", _BARBELL_UUID),
    ("Front Squat", _BARBELL_UUID),
    ("Barbell Lunge", _BARBELL_UUID),
    ("Romanian Deadlift", _BARBELL_UUID),
    ("Hip Thrust", _BARBELL_UUID),
    ("Glute Bridge", _BARBELL_UUID),
    ("Standing Calf Raise", _BARBELL_UUID),
    ("Seated Calf Raise", _BARBELL_UUID),
    # ── dumbbell (12개) ──────────────────────────────────────────────────────
    ("Dumbbell Fly", _DUMBBELL_UUID),
    ("One Arm Dumbbell Row", _DUMBBELL_UUID),
    ("Dumbbell Shrug", _DUMBBELL_UUID),
    ("Dumbbell Shoulder Press", _DUMBBELL_UUID),
    ("Front Raise", _DUMBBELL_UUID),
    ("Side Lateral Raise", _DUMBBELL_UUID),
    ("Rear Delt Raise", _DUMBBELL_UUID),
    ("Dumbbell Curl", _DUMBBELL_UUID),
    ("Dumbbell Hammer Curl", _DUMBBELL_UUID),
    ("Overhead Triceps Extension", _DUMBBELL_UUID),
    ("Side Bend", _DUMBBELL_UUID),
    ("Bulgarian Split Squat", _DUMBBELL_UUID),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. exercises upsert ──────────────────────────────────────────────────
    # ON CONFLICT(name_en) DO UPDATE: gif_url, category 갱신
    for name_ko, name_en, category, gif_url in _EXERCISES:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercises (id, name, name_en, category, gif_url, created_at, updated_at)
                VALUES (gen_random_uuid(), :name, :name_en, :category, :gif_url, now(), now())
                ON CONFLICT (name_en) DO UPDATE
                    SET gif_url    = EXCLUDED.gif_url,
                        category   = EXCLUDED.category,
                        updated_at = now()
                """
            ),
            {
                "name": name_ko,
                "name_en": name_en,
                "category": category,
                "gif_url": gif_url,
            },
        )

    # ── 2. exercise_muscles — name_en + slug JOIN, 결정론적 삽입 ─────────────
    for name_en, muscle_slug, involvement in _EXERCISE_MUSCLES:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercise_muscles (exercise_id, muscle_group_id, involvement, activation_pct)
                SELECT e.id, mg.id, :involvement, NULL
                FROM   exercises     e
                JOIN   muscle_groups mg ON mg.name = :muscle_slug
                WHERE  e.name_en = :name_en
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "name_en": name_en,
                "muscle_slug": muscle_slug,
                "involvement": involvement,
            },
        )

    # ── 3. exercise_equipment_map — name_en JOIN + 제네릭 기구 UUID ───────────
    for name_en, equipment_uuid in _EXERCISE_EQUIPMENT_MAP:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercise_equipment_map (exercise_id, equipment_id)
                SELECT e.id, :equipment_id
                FROM   exercises e
                WHERE  e.name_en = :name_en
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "name_en": name_en,
                "equipment_id": equipment_uuid,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()

    # ── 1. exercise_equipment_map — 이 시드가 넣은 쌍만 한정 삭제 ─────────────
    for name_en, equipment_uuid in _EXERCISE_EQUIPMENT_MAP:
        conn.execute(
            sa.text(
                """
                DELETE FROM exercise_equipment_map
                WHERE exercise_id = (SELECT id FROM exercises WHERE name_en = :name_en)
                  AND equipment_id = :equipment_id
                """
            ),
            {
                "name_en": name_en,
                "equipment_id": equipment_uuid,
            },
        )

    # ── 2. exercises 삭제 (cascade로 exercise_muscles도 삭제됨) ───────────────
    name_ens = [row[1] for row in _EXERCISES]
    if name_ens:
        conn.execute(
            sa.text("DELETE FROM exercises WHERE name_en = ANY(:names)"),
            {"names": name_ens},
        )
