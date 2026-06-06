"""muscle_groups 표준화 — 진짜 prod(hnwegx) 드리프트를 repo 슬러그 표준으로 정규화

Revision ID: 20260605_normalize_muscles
Revises: 20260605_fix_arm_eqmuscle
Create Date: 2026-06-05

배경 (진짜 prod 실측, 2026-06-05 read-only):
  라이브 prod 의 muscle_groups 가 repo 슬러그 표준에서 드리프트해 22종 중 9종이
  사람이 읽는 이름(Lats/Biceps/Triceps/Trapezius/Quadriceps/Hamstrings/Calves/
  Forearms/Upper Back)이고, body_region 에 'lower'/'upper' 혼입, 일부 name_ko 불일치
  (복근/둔근/어깨 전면…). 슬러그 표준 분류(repo Alembic 이 clean DB 에 생성하는 21종)와
  불일치해, 슬러그 기반 exercise_muscles 시드(후속 seed_activation 마이그)의 JOIN 이
  8개 근육에서 실패한다. 또 슬러그 표준엔 없는 'Upper Back'(상부 등)이 'Trapezius'(승모근)와
  별도 그룹으로 존재(구조 차이).

정규화 (이 마이그레이션):
  ① 사람이름 8종 → 슬러그 rename
  ② 21 표준 슬러그의 name_ko / body_region 을 정본값으로 정렬
  ③ 'Upper Back' → 'trapezius' 병합 (exercise_muscles / equipment_muscles 재지정,
     (exercise_id|equipment_id, muscle_group_id) PK 충돌 시 기존 trapezius 행 유지하고
     Upper Back 행 삭제) 후 그룹 삭제
  ④ 신규 5종 INSERT (adductors/serratus_anterior/levator_scapulae/brachialis/rotator_cuff)

★ muscle_group_id 하드코딩 절대 금지 — prod muscle id 는 환경마다 다르다. 전부 name 으로 해석.
멱등: clean DB(이미 슬러그 표준)에선 rename WHERE 0행, name_ko/region 동일, 'Upper Back' 없음,
  신규 5종 ON CONFLICT → 전 스텝 no-op. hnwegx(드리프트)에서만 실작동.
안전: muscle_groups/exercise_muscles/equipment_muscles 는 순수 참조 데이터 → 사용자
  루틴/기록과 무관(FK 는 exercise/equipment 경유, muscle_groups 직접참조 아님).
downgrade no-op: 정규화 역행(슬러그→사람이름 복원)은 무의미하며 정보 손실(병합)을 되돌릴 수 없음.
"""

from alembic import op

revision = "20260605_normalize_muscles"
down_revision = "20260605_fix_arm_eqmuscle"
branch_labels = None
depends_on = None

# ① 사람이름 → 슬러그 (slug 표준). clean DB 엔 좌변이 없어 0행 no-op.
_RENAMES = {
    "Lats": "latissimus_dorsi",
    "Biceps": "biceps_brachii",
    "Triceps": "triceps_brachii",
    "Trapezius": "trapezius",
    "Quadriceps": "quadriceps",
    "Hamstrings": "hamstrings",
    "Calves": "calves",
    "Forearms": "forearms",
}

# ② 21 표준 슬러그의 정본 (name_ko, body_region) — junpxp(clean Alembic 산출) 기준.
_CANON = {
    "biceps_brachii": ("이두근", "arms"),
    "triceps_brachii": ("삼두근", "arms"),
    "forearms": ("전완근", "arms"),
    "latissimus_dorsi": ("광배근", "back"),
    "trapezius": ("승모근", "back"),
    "rhomboids": ("능형근", "back"),
    "erector_spinae": ("척추기립근", "back"),
    "pectoralis_major": ("대흉근", "chest"),
    "pectoralis_minor": ("소흉근", "chest"),
    "rectus_abdominis": ("복직근", "core"),
    "obliques": ("복사근", "core"),
    "transverse_abdominis": ("심부 복근", "core"),
    "quadriceps": ("대퇴사두근", "legs"),
    "hamstrings": ("햄스트링", "legs"),
    "calves": ("종아리", "legs"),
    "gluteus_maximus": ("대둔근", "legs"),
    "gluteus_medius": ("중둔근", "legs"),
    "hip_flexors": ("고관절굴근", "legs"),
    "anterior_deltoid": ("전면 삼각근", "shoulders"),
    "lateral_deltoid": ("측면 삼각근", "shoulders"),
    "posterior_deltoid": ("후면 삼각근", "shoulders"),
}

# ④ 신규 5종 (slug, name_ko, body_region). vocab-26 결정.
_NEW5 = [
    ("adductors", "내전근", "legs"),
    ("serratus_anterior", "전거근", "chest"),
    ("levator_scapulae", "견갑거근", "back"),
    ("brachialis", "상완근", "arms"),
    ("rotator_cuff", "회전근개", "shoulders"),
]

_MERGE_SRC = "Upper Back"  # → trapezius 로 병합


def upgrade() -> None:
    conn = op.get_bind()
    from sqlalchemy import text

    # ① 사람이름 → 슬러그 rename. (clean DB: 좌변 미존재 → 0행)
    #    NOT EXISTS(우변) 가드 — 좌·우변이 동시 존재하는 비정상(수동편집) DB 에서도 duplicate key
    #    abort 대신 graceful skip (남은 좌변 행은 후속 ③ 병합/수동정리 대상). hnwegx/clean 엔 무영향.
    for old, new in _RENAMES.items():
        conn.execute(
            text(
                "UPDATE muscle_groups SET name = :new "
                "WHERE name = :old AND NOT EXISTS (SELECT 1 FROM muscle_groups WHERE name = :new)"
            ),
            {"new": new, "old": old},
        )

    # ② 표준 name_ko / body_region 정렬 (변경 필요한 행만 — 멱등).
    for slug, (name_ko, region) in _CANON.items():
        conn.execute(
            text(
                "UPDATE muscle_groups SET name_ko = :ko, body_region = :rg "
                "WHERE name = :slug AND (name_ko IS DISTINCT FROM :ko OR body_region IS DISTINCT FROM :rg)"
            ),
            {"ko": name_ko, "rg": region, "slug": slug},
        )

    # ③ 'Upper Back' → 'trapezius' 병합 (slug rename 이후라 'trapezius' 존재).
    #    clean DB: 'Upper Back' 미존재 → 전 스텝 no-op.
    for tbl, key in (("exercise_muscles", "exercise_id"), ("equipment_muscles", "equipment_id")):
        # 3a) 충돌 없는 행만 trapezius 로 재지정
        conn.execute(
            text(
                f"""
                UPDATE {tbl} m
                SET muscle_group_id = (SELECT id FROM muscle_groups WHERE name = 'trapezius')
                WHERE m.muscle_group_id = (SELECT id FROM muscle_groups WHERE name = :src)
                  AND NOT EXISTS (
                      SELECT 1 FROM {tbl} m2
                      WHERE m2.{key} = m.{key}
                        AND m2.muscle_group_id = (SELECT id FROM muscle_groups WHERE name = 'trapezius')
                  )
                """
            ),
            {"src": _MERGE_SRC},
        )
        # 3b) 충돌로 남은 Upper Back 행 삭제 (FK RESTRICT 해제용)
        conn.execute(
            text(f"DELETE FROM {tbl} WHERE muscle_group_id = (SELECT id FROM muscle_groups WHERE name = :src)"),
            {"src": _MERGE_SRC},
        )
    # 3c) 참조 0 된 Upper Back 그룹 삭제
    conn.execute(text("DELETE FROM muscle_groups WHERE name = :src"), {"src": _MERGE_SRC})

    # ④ 신규 5종 INSERT (멱등). name/name_ko 둘 다 UNIQUE 이므로 WHERE NOT EXISTS 로
    #    양쪽 충돌을 모두 차단 — ON CONFLICT(name) 만으론 name_ko 중복 시 abort 가능(M2 가드).
    for slug, name_ko, region in _NEW5:
        conn.execute(
            text(
                """
                INSERT INTO muscle_groups (id, name, name_ko, body_region)
                SELECT gen_random_uuid(), CAST(:slug AS varchar), CAST(:ko AS varchar), CAST(:rg AS varchar)
                WHERE NOT EXISTS (
                    SELECT 1 FROM muscle_groups WHERE name = CAST(:slug AS varchar) OR name_ko = CAST(:ko AS varchar)
                )
                """
            ),
            {"slug": slug, "ko": name_ko, "rg": region},
        )


def downgrade() -> None:
    # no-op: 정규화 역행은 정보 손실(Upper Back 병합)을 되돌릴 수 없고 의미 없음.
    pass
