"""WorkoutX 재시드 — muscle_groups(20) + equipment_brands(14)/equipments(132)/gym_equipments(33)
+ exercises(1318) + exercise_muscles. clean_slate_reseed 가 비운 레퍼런스를 채운다.

Revision ID: 20260606_reseed_workoutx
Revises: 20260606_clean_slate_reseed
Create Date: 2026-06-06

배경:
  CLAUDE.md §16 — 레퍼런스 데이터(근육군/운동/기구/헬스장)는 `alembic upgrade head` 로만 시드.
  seed.py / mlops 스크립트 수동 실행 금지. clean_slate_reseed(직전 revision)가 wipe 한 레퍼런스를
  채우는 재시드도 반드시 마이그레이션이어야 한다. 본 마이그가 그 정본이다.
  (mlops/scripts/seed_reference_data.py + seed_exercises_workoutx.py 의 시드 로직을 이식했다 —
   두 스크립트는 개발 보조로 유지될 수 있으나 prod 정본은 이 마이그.)

소스 데이터 (커밋 위치 = mlops/data/, Dockerfile 이 /app/mlops/data 로 복사):
  - reseed_equipment_brands.csv  (14)
  - reseed_equipments.csv        (132, is_freeweight 컬럼은 clean_slate Phase2e 에서 DROP → 제외)
  - reseed_gym_equipments.csv    (33, gym_id=더찬스짐 ecdd073b 만)
  - reseed_exercises_workoutx.json (1324 frozen → name_en dedup keep-last → 1318)
  muscle_groups(20)은 인라인 VALUES (muscle_normalization.md 기준).

적재 순서 (FK 안전):
  1) muscle_groups            (exercise_muscles.muscle_group_id FK)
  2) equipment_brands         (equipments.brand_id FK)
  3) equipments               (gym_equipments.equipment_id FK)
  4) gym_equipments           (gyms.id=더찬스짐 존재 전제 — 없으면 skip)
  5) exercises                (exercise_muscles.exercise_id FK)
  6) exercise_muscles         (muscle_groups + exercises 선적재 후, name JOIN)
  exercise_equipment junction 은 비운다 (Phase 7 Gemini 검증 산출물 전용).

멱등성: 모든 INSERT 는 ON CONFLICT DO UPDATE/DO NOTHING.

[논문 절대 불가침] papers / paper_chunks 에 대한 DELETE/DROP/ALTER 0건.
"""

import csv
import json
import logging
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "20260606_reseed_workoutx"
down_revision = "20260606_clean_slate_reseed"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic")

# ---------------------------------------------------------------------------
# 데이터 파일 경로 — 실행 환경별 다중 fallback (20260521_seed_equipments.py 패턴):
#   - Local alembic (cwd=repo_root): repo_root/mlops/data/...    (4 parent up)
#   - docker-compose / ECS Fargate (Dockerfile COPY mlops/data → /app/mlops/data): (3 parent up)
# 첫 번째로 존재하는 경로 채택.
# ---------------------------------------------------------------------------
_FILE = Path(__file__).resolve()


def _resolve_data(name: str) -> Path:
    candidates = [
        _FILE.parent.parent.parent.parent / "mlops" / "data" / name,
        _FILE.parent.parent.parent / "mlops" / "data" / name,
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


_BRANDS_CSV = _resolve_data("reseed_equipment_brands.csv")
_EQUIPMENTS_CSV = _resolve_data("reseed_equipments.csv")
_GYM_EQUIPMENTS_CSV = _resolve_data("reseed_gym_equipments.csv")
_EXERCISES_JSON = _resolve_data("reseed_exercises_workoutx.json")

# ---------------------------------------------------------------------------
# muscle_groups 20 캐노니컬 (muscle_normalization.md 기준)
#   name: Title-Case (WorkoutX API target 원문)  /  name_ko: 해부학 한국어
#   body_region: upper_body / lower_body / core / cardio
# ---------------------------------------------------------------------------
_MUSCLE_GROUPS: list[dict] = [
    {"name": "Abs", "name_ko": "복근", "body_region": "core"},
    {"name": "Pectorals", "name_ko": "대흉근", "body_region": "upper_body"},
    {"name": "Biceps", "name_ko": "이두근", "body_region": "upper_body"},
    {"name": "Glutes", "name_ko": "둔근", "body_region": "lower_body"},
    {"name": "Delts", "name_ko": "삼각근", "body_region": "upper_body"},
    {"name": "Triceps", "name_ko": "삼두근", "body_region": "upper_body"},
    {"name": "Upper Back", "name_ko": "상배근", "body_region": "upper_body"},
    {"name": "Lats", "name_ko": "광배근", "body_region": "upper_body"},
    {"name": "Calves", "name_ko": "종아리", "body_region": "lower_body"},
    {"name": "Quads", "name_ko": "대퇴사두근", "body_region": "lower_body"},
    {"name": "Forearms", "name_ko": "전완근", "body_region": "upper_body"},
    {"name": "Cardiovascular System", "name_ko": "심혈관계", "body_region": "cardio"},
    {"name": "Hamstrings", "name_ko": "햄스트링", "body_region": "lower_body"},
    {"name": "Spine", "name_ko": "척추기립근", "body_region": "upper_body"},
    {"name": "Traps", "name_ko": "승모근", "body_region": "upper_body"},
    {"name": "Adductors", "name_ko": "내전근", "body_region": "lower_body"},
    {"name": "Serratus Anterior", "name_ko": "전거근", "body_region": "upper_body"},
    {"name": "Abductors", "name_ko": "외전근", "body_region": "lower_body"},
    {"name": "Levator Scapulae", "name_ko": "견갑거근", "body_region": "upper_body"},
    {"name": "Hip Flexors", "name_ko": "고관절굴곡근", "body_region": "lower_body"},
]

_CANON_MUSCLE_NAMES: frozenset[str] = frozenset(mg["name"] for mg in _MUSCLE_GROUPS)

# ---------------------------------------------------------------------------
# load_mode 매핑 — WorkoutX equipment 문자열(lower) → 11종 canonical load_mode.
# SOT: server/app/api/v1/admin.py:_WX_LOAD_MODE + mlops/scripts/seed_exercises_workoutx.py.
# frozen exercises.json(1324)의 34종 distinct equipment 문자열을 전수 매핑.
# 미지원값은 skip 이 아닌 fail-fast(ValueError) — NULL load_mode garbage 방지.
# ---------------------------------------------------------------------------
_WX_LOAD_MODE: dict[str, str] = {
    # barbell 계열 (ez/trap 별도)
    "barbell": "barbell",
    "olympic barbell": "barbell",
    "ez barbell": "ez_barbell",
    "ez barbell, exercise ball": "ez_barbell",
    "trap bar": "trap_bar",
    # dumbbell 계열
    "dumbbell": "dumbbell",
    "dumbbell (used as handles for deeper range)": "dumbbell",
    "dumbbell, exercise ball": "dumbbell",
    "dumbbell, exercise ball, tennis ball": "dumbbell",
    # bodyweight 계열
    "body weight": "bodyweight",
    "body weight (with resistance band)": "bodyweight",
    "stability ball": "bodyweight",
    "bosu ball": "bodyweight",
    "roller": "bodyweight",
    "wheel roller": "bodyweight",
    "medicine ball": "bodyweight",
    "rope": "bodyweight",
    # weighted (체중 + 외부 부하)
    "weighted": "weighted",
    # kettlebell
    "kettlebell": "kettlebell",
    # band
    "band": "band",
    "resistance band": "band",
    # cable
    "cable": "cable",
    # machine 계열
    "leverage machine": "machine",
    "smith machine": "machine",
    "assisted": "machine",
    "assisted (towel)": "machine",
    "sled machine": "machine",
    "hammer": "machine",
    "tire": "machine",
    # cardio (부하 개념 없음)
    "stationary bike": "cardio",
    "upper body ergometer": "cardio",
    "elliptical machine": "cardio",
    "skierg machine": "cardio",
    "stepmill machine": "cardio",
}


def _resolve_load_mode(wx_equipment: str) -> str:
    """WorkoutX equipment 문자열 → canonical load_mode. 미지원값은 fail-fast(ValueError)."""
    key = (wx_equipment or "").strip().lower()
    try:
        return _WX_LOAD_MODE[key]
    except KeyError as e:
        raise ValueError(
            f"매핑되지 않은 WorkoutX equipment: {wx_equipment!r} (lower={key!r}). "
            "_WX_LOAD_MODE 에 추가하거나 데이터를 확인하세요 (fail-fast)."
        ) from e


# ---------------------------------------------------------------------------
# secondaryMuscles → canon-20 정규화 맵.
# SOT: docs/handoff/workoutx-raw/muscle_normalization.md L20-54 (35행 전체, identity 포함).
# DROP 5종(Ankles/Feet/Ankle Stabilizers/Hands/Shins)은 본 맵 제외 → secondary 미생성.
# 정규화 후 primary(target)와 같은 canon 이면 primary 우선(secondary 무시).
# ---------------------------------------------------------------------------
_SECONDARY_TO_CANON: dict[str, str] = {
    "Shoulders": "Delts",
    "Hamstrings": "Hamstrings",
    "Forearms": "Forearms",
    "Triceps": "Triceps",
    "Biceps": "Biceps",
    "Quadriceps": "Quads",
    "Calves": "Calves",
    "Glutes": "Glutes",
    "Core": "Abs",
    "Chest": "Pectorals",
    "Hip Flexors": "Hip Flexors",
    "Obliques": "Abs",
    "Lower Back": "Spine",
    "Rhomboids": "Upper Back",
    "Trapezius": "Traps",
    "Upper Back": "Upper Back",
    "Traps": "Traps",
    "Deltoids": "Delts",
    "Rear Deltoids": "Delts",
    "Brachialis": "Biceps",
    "Back": "Spine",
    "Rotator Cuff": "Delts",
    "Latissimus Dorsi": "Lats",
    "Soleus": "Calves",
    "Upper Chest": "Pectorals",
    "Wrists": "Forearms",
    "Wrist Extensors": "Forearms",
    "Wrist Flexors": "Forearms",
    "Sternocleidomastoid": "Levator Scapulae",
    "Abdominals": "Abs",
    "Grip Muscles": "Forearms",
    "Lower Abs": "Abs",
    "Inner Thighs": "Adductors",
    "Groin": "Adductors",
    "Lats": "Lats",
}

# 근육 아님/잡값 — secondary 에서 제외.
_SECONDARY_DROP: frozenset[str] = frozenset({"Ankles", "Feet", "Ankle Stabilizers", "Hands", "Shins"})


def _normalize_secondary(raw: str) -> str | None:
    """secondaryMuscles 원소 → canon-20 또는 None(drop/미매핑)."""
    name = (raw or "").strip()
    if not name or name in _SECONDARY_DROP:
        return None
    return _SECONDARY_TO_CANON.get(name)


# ---------------------------------------------------------------------------
# CSV/JSON 파싱 헬퍼
# ---------------------------------------------------------------------------
def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _opt_str(val: str | None) -> str | None:
    v = (val or "").strip()
    return v or None


def _opt_float(val: str | None) -> float | None:
    v = (val or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _parse_bool(val: str | None) -> bool:
    return (val or "").strip().upper() in ("TRUE", "1", "YES")


def _opt_jsonb(val: str | None) -> str | None:
    """stack_weight JSONB 원문(문자열) 반환. CAST(:x AS jsonb) 로 적재. 빈값/불량 → None."""
    v = (val or "").strip()
    if not v:
        return None
    try:
        json.loads(v)  # 유효성만 검증
    except json.JSONDecodeError:
        return None
    return v


def _load_exercises() -> list[dict]:
    """frozen exercises.json 로드 후 name_en dedup(keep-last) → 1318."""
    with open(_EXERCISES_JSON, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "data" in data:
        items = data["data"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"예상치 못한 exercises.json 구조: {type(data).__name__}")

    # name_en(=name) dedup, keep-last — 6건 중복이 단일 배치 ON CONFLICT 에서
    # CardinalityViolation 을 유발하므로 사전 제거.
    by_name: dict[str, dict] = {}
    for ex in items:
        name_en = (ex.get("name") or "").strip()
        if not name_en:
            continue
        by_name[name_en] = ex
    return list(by_name.values())


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------
def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # 1) muscle_groups (20 canon) — name(UNIQUE) conflict → name_ko/body_region 갱신.
    # =========================================================================
    mg_rows = [
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"muscle_group:{mg['name']}")),
            "name": mg["name"],
            "name_ko": mg["name_ko"],
            "body_region": mg["body_region"],
        }
        for mg in _MUSCLE_GROUPS
    ]
    conn.execute(
        sa.text(
            """
            INSERT INTO muscle_groups (id, name, name_ko, body_region)
            VALUES (:id, :name, :name_ko, :body_region)
            ON CONFLICT (name) DO UPDATE
                SET name_ko     = EXCLUDED.name_ko,
                    body_region = EXCLUDED.body_region
            """
        ),
        mg_rows,
    )
    logger.info("reseed: muscle_groups upsert %d건", len(mg_rows))

    # =========================================================================
    # 2) equipment_brands (14) — id(UNIQUE) conflict → 메타 갱신.
    # =========================================================================
    brand_rows = []
    for r in _read_csv(_BRANDS_CSV):
        brand_rows.append(
            {
                "id": r["id"].strip(),
                "name": r["name"].strip(),
                "logo_url": _opt_str(r.get("logo_url")),
                "default_bar_unit": (r.get("default_bar_unit") or "kg").strip() or "kg",
                "default_stack_unit": (r.get("default_stack_unit") or "kg").strip() or "kg",
            }
        )
    conn.execute(
        sa.text(
            """
            INSERT INTO equipment_brands (id, name, logo_url, default_bar_unit, default_stack_unit)
            VALUES (:id, :name, :logo_url, :default_bar_unit, :default_stack_unit)
            ON CONFLICT (id) DO UPDATE
                SET name               = EXCLUDED.name,
                    logo_url           = EXCLUDED.logo_url,
                    default_bar_unit   = EXCLUDED.default_bar_unit,
                    default_stack_unit = EXCLUDED.default_stack_unit
            """
        ),
        brand_rows,
    )
    logger.info("reseed: equipment_brands upsert %d건", len(brand_rows))

    # =========================================================================
    # 3) equipments (132) — id conflict → 전 컬럼 갱신. is_freeweight 컬럼은 제외
    #    (clean_slate Phase2e 에서 DROP). stack_weight 는 CAST(... AS jsonb).
    # =========================================================================
    eq_rows = []
    for r in _read_csv(_EQUIPMENTS_CSV):
        bid = (r.get("brand_id") or "").strip()
        eq_rows.append(
            {
                "id": r["id"].strip(),
                "brand_id": bid or None,
                "name": r["name"].strip(),
                "name_en": _opt_str(r.get("name_en")),
                "category": _opt_str(r.get("category")),
                "sub_category": _opt_str(r.get("sub_category")),
                "equipment_type": r["equipment_type"].strip(),
                "pulley_ratio": _opt_float(r.get("pulley_ratio")) or 1.0,
                "bar_weight": _opt_float(r.get("bar_weight")),
                "bar_weight_unit": _opt_str(r.get("bar_weight_unit")),
                "has_weight_assist": _parse_bool(r.get("has_weight_assist")),
                "min_stack": _opt_float(r.get("min_stack")),
                "max_stack": _opt_float(r.get("max_stack")),
                "stack_weight": _opt_jsonb(r.get("stack_weight")),
                "stack_unit": _opt_str(r.get("stack_unit")),
                "image_url": _opt_str(r.get("image_url")),
            }
        )
    conn.execute(
        sa.text(
            """
            INSERT INTO equipments (
                id, brand_id, name, name_en, category, sub_category, equipment_type,
                pulley_ratio, bar_weight, bar_weight_unit, has_weight_assist,
                min_stack, max_stack, stack_weight, stack_unit, image_url
            ) VALUES (
                :id, :brand_id, :name, :name_en, :category, :sub_category, :equipment_type,
                :pulley_ratio, :bar_weight, :bar_weight_unit, :has_weight_assist,
                :min_stack, :max_stack, CAST(:stack_weight AS jsonb), :stack_unit, :image_url
            )
            ON CONFLICT (id) DO UPDATE
                SET brand_id          = EXCLUDED.brand_id,
                    name              = EXCLUDED.name,
                    name_en           = EXCLUDED.name_en,
                    category          = EXCLUDED.category,
                    sub_category      = EXCLUDED.sub_category,
                    equipment_type    = EXCLUDED.equipment_type,
                    pulley_ratio      = EXCLUDED.pulley_ratio,
                    bar_weight        = EXCLUDED.bar_weight,
                    bar_weight_unit   = EXCLUDED.bar_weight_unit,
                    has_weight_assist = EXCLUDED.has_weight_assist,
                    min_stack         = EXCLUDED.min_stack,
                    max_stack         = EXCLUDED.max_stack,
                    stack_weight      = EXCLUDED.stack_weight,
                    stack_unit        = EXCLUDED.stack_unit,
                    image_url         = EXCLUDED.image_url
            """
        ),
        eq_rows,
    )
    logger.info("reseed: equipments upsert %d건", len(eq_rows))

    # =========================================================================
    # 4) gym_equipments (33) — gyms.id(더찬스짐 ecdd073b) 존재 전제.
    #    누락 시 FK 위반 방지를 위해 존재하는 gym_id 행만 적재(경고).
    # =========================================================================
    ge_raw = _read_csv(_GYM_EQUIPMENTS_CSV)
    gym_ids = {r["gym_id"].strip() for r in ge_raw}
    existing = {
        str(row[0])
        for row in conn.execute(
            sa.text("SELECT id FROM gyms WHERE id = ANY(:ids)"),
            {"ids": list(gym_ids)},
        )
    }
    missing = gym_ids - existing
    if missing:
        logger.warning("reseed: gym_equipments — gyms 에 없는 gym_id skip: %s", missing)

    ge_rows = []
    for r in ge_raw:
        gid = r["gym_id"].strip()
        if gid not in existing:
            continue
        ge_rows.append(
            {
                "gym_id": gid,
                "equipment_id": r["equipment_id"].strip(),
                "quantity": int((r.get("quantity") or "1").strip() or "1"),
            }
        )
    if ge_rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO gym_equipments (gym_id, equipment_id, quantity)
                VALUES (:gym_id, :equipment_id, :quantity)
                ON CONFLICT (gym_id, equipment_id) DO UPDATE
                    SET quantity = EXCLUDED.quantity
                """
            ),
            ge_rows,
        )
        logger.info("reseed: gym_equipments upsert %d건", len(ge_rows))
    else:
        logger.warning("reseed: gym_equipments 적재 0건 (gyms 에 더찬스짐 없음)")

    # =========================================================================
    # 5) exercises (1318) — category=bodyPart 원문, load_mode(fail-fast).
    #    name_en(UNIQUE) conflict → 갱신. id 는 결정론적 uuid5(name_en).
    # =========================================================================
    exercises = _load_exercises()
    ex_rows = []
    for ex in exercises:
        name_en = (ex.get("name") or "").strip()
        body_part = (ex.get("bodyPart") or "").strip()
        if not name_en or not body_part:
            # category NOT NULL 방어 (frozen 데이터엔 없음)
            logger.warning("reseed: 운동 '%s' bodyPart 없음 skip", name_en)
            continue
        load_mode = _resolve_load_mode(ex.get("equipment", ""))  # fail-fast
        ex_rows.append(
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"exercise:{name_en}")),
                "name": name_en,
                "name_en": name_en,
                "category": body_part,
                "gif_url": ex.get("gifUrl"),
                "load_mode": load_mode,
            }
        )
    conn.execute(
        sa.text(
            """
            INSERT INTO exercises (id, name, name_en, category, gif_url, load_mode, created_at, updated_at)
            VALUES (:id, :name, :name_en, :category, :gif_url, :load_mode, now(), now())
            ON CONFLICT (name_en) DO UPDATE
                SET name       = EXCLUDED.name,
                    category   = EXCLUDED.category,
                    gif_url    = EXCLUDED.gif_url,
                    load_mode  = EXCLUDED.load_mode,
                    updated_at = now()
            """
        ),
        ex_rows,
    )
    logger.info("reseed: exercises upsert %d건", len(ex_rows))

    # =========================================================================
    # 6) exercise_muscles — primary=target, secondary=normalize(secondaryMuscles).
    #    name_en + muscle name JOIN 으로 DB 실제 id 해석(uuid5 skip 시에도 안전).
    #    primary 우선(같은 canon secondary 무시). activation_pct=NULL(후속 백필).
    #    (exercise_id, muscle_group_id) PK conflict → involvement 갱신.
    # =========================================================================
    em_params: list[dict] = []
    missing_target = 0
    for ex in exercises:
        name_en = (ex.get("name") or "").strip()
        if not name_en:
            continue

        per_ex: dict[str, str] = {}  # canon muscle name → involvement

        target = (ex.get("target") or "").strip()
        if target in _CANON_MUSCLE_NAMES:
            per_ex[target] = "primary"
        else:
            missing_target += 1
            logger.warning("reseed: 운동 '%s' target '%s' canon 외, primary skip", name_en, target)

        for raw in ex.get("secondaryMuscles") or []:
            canon = _normalize_secondary(raw)
            if canon is None or canon not in _CANON_MUSCLE_NAMES:
                continue
            if canon in per_ex:
                continue  # primary(또는 기존 secondary) 우선
            per_ex[canon] = "secondary"

        for muscle_name, involvement in per_ex.items():
            em_params.append(
                {
                    "name_en": name_en,
                    "muscle_name": muscle_name,
                    "involvement": involvement,
                }
            )

    if missing_target:
        logger.warning("reseed: exercise_muscles — target canon 누락 %d운동 primary skip", missing_target)

    # name JOIN 단건 실행(결정론적·안전). exercises/muscle_groups 선적재 완료 상태.
    for p in em_params:
        conn.execute(
            sa.text(
                """
                INSERT INTO exercise_muscles (exercise_id, muscle_group_id, involvement, activation_pct)
                SELECT e.id, mg.id, :involvement, NULL
                FROM   exercises     e
                JOIN   muscle_groups mg ON mg.name = :muscle_name
                WHERE  e.name_en = :name_en
                ON CONFLICT (exercise_id, muscle_group_id) DO UPDATE
                    SET involvement = EXCLUDED.involvement
                """
            ),
            p,
        )
    logger.info("reseed: exercise_muscles upsert %d건", len(em_params))

    # exercise_equipment junction 은 채우지 않는다 (Phase 7 Gemini 검증 전용).


def downgrade() -> None:
    """재시드 데이터 DELETE (FK 역순). 루틴/로그/1rm 은 본 마이그가 만들지 않으므로 미접촉.

    forward-only 운영 권장이나, 적재분만 한정 삭제하는 역연산을 제공한다.
    [논문 불가침] papers/paper_chunks 미접촉.
    """
    conn = op.get_bind()

    # 6) exercise_muscles — 본 마이그가 적재한 운동의 매핑 전체 삭제.
    exercises = _load_exercises()
    name_ens = [(ex.get("name") or "").strip() for ex in exercises if (ex.get("name") or "").strip()]
    if name_ens:
        conn.execute(
            sa.text(
                """
                DELETE FROM exercise_muscles
                WHERE exercise_id IN (SELECT id FROM exercises WHERE name_en = ANY(:names))
                """
            ),
            {"names": name_ens},
        )
        # 5) exercises
        conn.execute(
            sa.text("DELETE FROM exercises WHERE name_en = ANY(:names)"),
            {"names": name_ens},
        )

    # 4) gym_equipments
    ge_ids = [r["equipment_id"].strip() for r in _read_csv(_GYM_EQUIPMENTS_CSV)]
    if ge_ids:
        conn.execute(
            sa.text("DELETE FROM gym_equipments WHERE equipment_id = ANY(:ids)"),
            {"ids": ge_ids},
        )

    # 3) equipments
    eq_ids = [r["id"].strip() for r in _read_csv(_EQUIPMENTS_CSV)]
    if eq_ids:
        conn.execute(
            sa.text("DELETE FROM equipments WHERE id = ANY(:ids)"),
            {"ids": eq_ids},
        )

    # 2) equipment_brands
    brand_ids = [r["id"].strip() for r in _read_csv(_BRANDS_CSV)]
    if brand_ids:
        conn.execute(
            sa.text("DELETE FROM equipment_brands WHERE id = ANY(:ids)"),
            {"ids": brand_ids},
        )

    # 1) muscle_groups
    mg_names = [mg["name"] for mg in _MUSCLE_GROUPS]
    if mg_names:
        conn.execute(
            sa.text("DELETE FROM muscle_groups WHERE name = ANY(:names)"),
            {"names": mg_names},
        )
