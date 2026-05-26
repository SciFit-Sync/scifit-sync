"""muscle_groups + exercises seed data (주요 근육 그룹 및 운동 목록)

Revision ID: 20260525_seed_muscle_groups_exercises
Revises: 20260524_seed_ai_gym_equipments
Create Date: 2026-05-25

멱등성: ON CONFLICT DO NOTHING — UNIQUE 충돌 시 skip.
UUID: uuid5(NAMESPACE_DNS, slug) 로 결정론적 생성.
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "20260525_seed_exercises"
down_revision = "20260525_add_gif_url_exercises"
branch_labels = None
depends_on = None


# ── 결정론적 UUID 헬퍼 ─────────────────────────────────────────────────────────
def _uid(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, slug))


# ── muscle_groups ─────────────────────────────────────────────────────────────
# (name, name_ko, body_region)
_MUSCLE_GROUPS = [
    # 가슴
    ("pectoralis_major", "대흉근", "chest"),
    ("pectoralis_minor", "소흉근", "chest"),
    # 등
    ("latissimus_dorsi", "광배근", "back"),
    ("rhomboids", "능형근", "back"),
    ("trapezius", "승모근", "back"),
    ("erector_spinae", "척추기립근", "back"),
    # 어깨
    ("anterior_deltoid", "전면 삼각근", "shoulders"),
    ("lateral_deltoid", "측면 삼각근", "shoulders"),
    ("posterior_deltoid", "후면 삼각근", "shoulders"),
    # 팔
    ("biceps_brachii", "이두근", "arms"),
    ("triceps_brachii", "삼두근", "arms"),
    ("forearms", "전완근", "arms"),
    # 복근/코어
    ("rectus_abdominis", "복직근", "core"),
    ("obliques", "복사근", "core"),
    ("transverse_abdominis", "심부 복근", "core"),
    # 하체
    ("quadriceps", "대퇴사두근", "legs"),
    ("hamstrings", "햄스트링", "legs"),
    ("gluteus_maximus", "대둔근", "legs"),
    ("gluteus_medius", "중둔근", "legs"),
    ("calves", "종아리", "legs"),
    ("hip_flexors", "고관절굴근", "legs"),
]

# ── exercises ─────────────────────────────────────────────────────────────────
# (name_ko, name_en, category, description)
_EXERCISES = [
    # ── 가슴 ──────────────────────────────────────────────
    ("벤치프레스", "Bench Press", "chest", "바벨을 이용한 가슴 대표 운동"),
    ("인클라인 벤치프레스", "Incline Bench Press", "chest", "상부 가슴을 집중 자극하는 경사 벤치 운동"),
    ("덤벨 플라이", "Dumbbell Fly", "chest", "가슴 내외측을 스트레치하는 운동"),
    ("딥스", "Dips", "chest", "자체 체중을 이용한 가슴·삼두 운동"),
    ("케이블 크로스오버", "Cable Crossover", "chest", "케이블을 이용한 가슴 고립 운동"),
    # ── 등 ────────────────────────────────────────────────
    ("데드리프트", "Conventional Deadlift", "back", "전신 근육을 동원하는 대표 복합 운동"),
    ("바벨 로우", "Barbell Row", "back", "광배근 중심의 복합 당기기 운동"),
    ("풀업", "Pull Up", "back", "체중을 이용한 광배근 운동"),
    ("시티드 로우", "Seated Cable Row", "back", "케이블로 등 중부를 자극하는 운동"),
    ("랫 풀다운", "Lat Pulldown", "back", "케이블로 광배근을 단련하는 운동"),
    # ── 어깨 ──────────────────────────────────────────────
    ("오버헤드프레스", "Overhead Press", "shoulders", "바벨로 전·측면 삼각근을 단련하는 운동"),
    ("덤벨 숄더프레스", "Dumbbell Shoulder Press", "shoulders", "덤벨로 어깨 전체를 자극하는 운동"),
    ("사이드 레터럴 레이즈", "Side Lateral Raise", "shoulders", "측면 삼각근을 고립하는 운동"),
    ("페이스풀", "Face Pull", "shoulders", "후면 삼각근·회전근개를 자극하는 운동"),
    # ── 팔 ────────────────────────────────────────────────
    ("바벨 컬", "Barbell Curl", "arms", "바벨로 이두근을 단련하는 운동"),
    ("덤벨 해머 컬", "Dumbbell Hammer Curl", "arms", "이두근·전완근을 동시에 자극하는 운동"),
    ("트라이셉 푸시다운", "Tricep Pushdown", "arms", "케이블로 삼두근을 고립하는 운동"),
    ("스컬크러셔", "Skull Crusher", "arms", "바벨로 삼두근 장두를 자극하는 운동"),
    # ── 복근/코어 ─────────────────────────────────────────
    ("플랭크", "Plank", "core", "코어 안정성을 기르는 등척성 운동"),
    ("크런치", "Crunch", "core", "복직근을 고립하는 기본 복근 운동"),
    ("케이블 크런치", "Cable Crunch", "core", "케이블로 저항을 추가한 복근 운동"),
    # ── 하체 ──────────────────────────────────────────────
    ("백 스쿼트", "Back Squat", "legs", "하체 전체를 동원하는 대표 복합 운동"),
    ("레그프레스", "Leg Press", "legs", "머신으로 대퇴사두를 자극하는 운동"),
    ("레그 익스텐션", "Leg Extension", "legs", "대퇴사두근을 고립하는 머신 운동"),
    ("레그 컬", "Leg Curl", "legs", "햄스트링을 고립하는 머신 운동"),
    ("루마니안 데드리프트", "Romanian Deadlift", "legs", "햄스트링·둔근을 집중 자극하는 운동"),
    ("힙 스러스트", "Hip Thrust", "legs", "둔근을 집중 자극하는 운동"),
    ("카프 레이즈", "Calf Raise", "legs", "종아리 근육을 강화하는 운동"),
]

# ── exercise → primary muscle 매핑 ───────────────────────────────────────────
# (name_en, muscle_slug, involvement)
_EXERCISE_MUSCLES = [
    # 벤치프레스
    ("Bench Press", "pectoralis_major", "primary"),
    ("Bench Press", "anterior_deltoid", "secondary"),
    ("Bench Press", "triceps_brachii", "secondary"),
    # 인클라인 벤치프레스
    ("Incline Bench Press", "pectoralis_major", "primary"),
    ("Incline Bench Press", "anterior_deltoid", "secondary"),
    ("Incline Bench Press", "triceps_brachii", "secondary"),
    # 덤벨 플라이
    ("Dumbbell Fly", "pectoralis_major", "primary"),
    ("Dumbbell Fly", "pectoralis_minor", "secondary"),
    # 딥스
    ("Dips", "pectoralis_major", "primary"),
    ("Dips", "triceps_brachii", "secondary"),
    # 케이블 크로스오버
    ("Cable Crossover", "pectoralis_major", "primary"),
    # 데드리프트
    ("Conventional Deadlift", "erector_spinae", "primary"),
    ("Conventional Deadlift", "gluteus_maximus", "primary"),
    ("Conventional Deadlift", "hamstrings", "secondary"),
    ("Conventional Deadlift", "quadriceps", "secondary"),
    ("Conventional Deadlift", "trapezius", "secondary"),
    # 바벨 로우
    ("Barbell Row", "latissimus_dorsi", "primary"),
    ("Barbell Row", "rhomboids", "secondary"),
    ("Barbell Row", "biceps_brachii", "secondary"),
    # 풀업
    ("Pull Up", "latissimus_dorsi", "primary"),
    ("Pull Up", "biceps_brachii", "secondary"),
    # 시티드 로우
    ("Seated Cable Row", "latissimus_dorsi", "primary"),
    ("Seated Cable Row", "rhomboids", "secondary"),
    # 랫 풀다운
    ("Lat Pulldown", "latissimus_dorsi", "primary"),
    ("Lat Pulldown", "biceps_brachii", "secondary"),
    # 오버헤드프레스
    ("Overhead Press", "anterior_deltoid", "primary"),
    ("Overhead Press", "lateral_deltoid", "secondary"),
    ("Overhead Press", "triceps_brachii", "secondary"),
    # 덤벨 숄더프레스
    ("Dumbbell Shoulder Press", "anterior_deltoid", "primary"),
    ("Dumbbell Shoulder Press", "lateral_deltoid", "secondary"),
    # 사이드 레터럴 레이즈
    ("Side Lateral Raise", "lateral_deltoid", "primary"),
    # 페이스풀
    ("Face Pull", "posterior_deltoid", "primary"),
    ("Face Pull", "trapezius", "secondary"),
    # 바벨 컬
    ("Barbell Curl", "biceps_brachii", "primary"),
    ("Barbell Curl", "forearms", "secondary"),
    # 덤벨 해머 컬
    ("Dumbbell Hammer Curl", "biceps_brachii", "primary"),
    ("Dumbbell Hammer Curl", "forearms", "secondary"),
    # 트라이셉 푸시다운
    ("Tricep Pushdown", "triceps_brachii", "primary"),
    # 스컬크러셔
    ("Skull Crusher", "triceps_brachii", "primary"),
    # 플랭크
    ("Plank", "rectus_abdominis", "primary"),
    ("Plank", "transverse_abdominis", "primary"),
    ("Plank", "obliques", "secondary"),
    # 크런치
    ("Crunch", "rectus_abdominis", "primary"),
    # 케이블 크런치
    ("Cable Crunch", "rectus_abdominis", "primary"),
    ("Cable Crunch", "obliques", "secondary"),
    # 백 스쿼트
    ("Back Squat", "quadriceps", "primary"),
    ("Back Squat", "gluteus_maximus", "primary"),
    ("Back Squat", "hamstrings", "secondary"),
    ("Back Squat", "erector_spinae", "secondary"),
    # 레그프레스
    ("Leg Press", "quadriceps", "primary"),
    ("Leg Press", "gluteus_maximus", "secondary"),
    # 레그 익스텐션
    ("Leg Extension", "quadriceps", "primary"),
    # 레그 컬
    ("Leg Curl", "hamstrings", "primary"),
    # 루마니안 데드리프트
    ("Romanian Deadlift", "hamstrings", "primary"),
    ("Romanian Deadlift", "gluteus_maximus", "primary"),
    ("Romanian Deadlift", "erector_spinae", "secondary"),
    # 힙 스러스트
    ("Hip Thrust", "gluteus_maximus", "primary"),
    ("Hip Thrust", "gluteus_medius", "secondary"),
    ("Hip Thrust", "hamstrings", "secondary"),
    # 카프 레이즈
    ("Calf Raise", "calves", "primary"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. muscle_groups ─────────────────────────────────────────────────────
    mg_rows = [
        {
            "id": _uid(f"muscle_group:{slug}"),
            "name": slug,
            "name_ko": name_ko,
            "body_region": body_region,
        }
        for slug, name_ko, body_region in _MUSCLE_GROUPS
    ]
    conn.execute(
        sa.text(
            """
            INSERT INTO muscle_groups (id, name, name_ko, body_region)
            VALUES (:id, :name, :name_ko, :body_region)
            ON CONFLICT DO NOTHING
            """
        ),
        mg_rows,
    )

    # ── 2. exercises ─────────────────────────────────────────────────────────
    ex_rows = [
        {
            "id": _uid(f"exercise:{name_en}"),
            "name": name_ko,
            "name_en": name_en,
            "category": category,
            "description": description,
        }
        for name_ko, name_en, category, description in _EXERCISES
    ]
    conn.execute(
        sa.text(
            """
            INSERT INTO exercises (id, name, name_en, category, description, created_at, updated_at)
            VALUES (:id, :name, :name_en, :category, :description, now(), now())
            ON CONFLICT DO NOTHING
            """
        ),
        ex_rows,
    )

    # ── 3. exercise_muscles — DB에서 실제 ID를 JOIN으로 조회 ────────────────
    # exercises가 ON CONFLICT DO NOTHING으로 skip된 경우 uuid5 ID와 실제 DB ID가
    # 다를 수 있으므로 name_en / name 기반 JOIN으로 안전하게 삽입한다.
    for name_en, muscle_slug, involvement in _EXERCISE_MUSCLES:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercise_muscles (exercise_id, muscle_group_id, involvement, activation_pct)
                SELECT e.id, mg.id, :involvement, NULL
                FROM exercises e, muscle_groups mg
                WHERE e.name_en = :name_en
                  AND mg.name   = :muscle_slug
                ON CONFLICT DO NOTHING
                """
            ),
            {"name_en": name_en, "muscle_slug": muscle_slug, "involvement": involvement},
        )


def downgrade() -> None:
    conn = op.get_bind()

    ex_ids = [_uid(f"exercise:{name_en}") for _, name_en, _, _ in _EXERCISES]
    mg_ids = [_uid(f"muscle_group:{slug}") for slug, _, _ in _MUSCLE_GROUPS]

    if ex_ids:
        conn.execute(
            sa.text("DELETE FROM exercises WHERE id = ANY(:ids)"),
            {"ids": ex_ids},
        )
    if mg_ids:
        conn.execute(
            sa.text("DELETE FROM muscle_groups WHERE id = ANY(:ids)"),
            {"ids": mg_ids},
        )
