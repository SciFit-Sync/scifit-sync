"""equipment_muscles 팔 교정 — Cable garbage 제거 + Assisted Dip/Chin triceps 복구

Revision ID: 20260605_fix_arm_equipment_muscles
Revises: 20260605_recover_default_equip
Create Date: 2026-06-05

배경 (더찬스짐 '팔→전신' 데이터 품질 이슈):
  PR-1(equipment_centric_pr1)이 exercise_equipment_map(eem) ⋈ exercise_muscles 경로로
  아래 3개 기구에 전신운동을 잘못 엮어 잡탕 primary 를 백필했다(prod 실측):
    - bf3d0dde 'Cable' (category=back, movement_label_en='Machine Lat Pulldown'):
        primary = lateral_deltoid/pectoralis_major/posterior_deltoid/rectus_abdominis/triceps_brachii (5개 garbage)
    - e94bec5c 'Cable' : bf3d0dde 와 동일
    - 2ca108c5 'Assisted Dip/Chin' (category=arms, movement_label_en='Cable Triceps Pushdown'):
        primary = latissimus_dorsi/pectoralis_major, secondary = biceps_brachii/triceps_brachii
  나중 실행된 eqmuscle_direct(movement_label_en→exercises.name_en JOIN)는 '정답'을 계산하지만
  ON CONFLICT DO NOTHING(20260604_eqmuscle_direct.py) 때문에 PK(equipment_id, muscle_group_id)
  충돌로 전량 silent drop 됐다. → 단순 INSERT/재실행은 NO-OP. **DELETE-먼저가 유일 경로.**

  증상: triceps=primary 인 Cable 2개가 '머신 팔 필터'(involvement='primary')에 등 레이블로
  끼어들고, 진짜 팔 기구 Assisted Dip/Chin 은 triceps=secondary 라 필터에서 누락 →
  팔 루틴에 등/가슴/어깨가 섞이고 정작 삼두 기구는 빠짐.

교정 (외과적, 3개 equipment_id 한정):
  STEP1) 3개 기구의 equipment_muscles 전량 DELETE (PK 충돌 우회).
  STEP2) eqmuscle_direct 의 movement_label_en→name_en JOIN 을 3개 id 로 SCOPE 해 replay INSERT.
  prod 실측 검증(read-only)으로 산출 행 확정:
    - bf3d0dde/e94bec5c → latissimus_dorsi PRIMARY (등, category 정합 → 팔 필터에서 배제)
    - 2ca108c5         → triceps_brachii  PRIMARY (팔, 머신 팔 필터에 포착)

★ muscle_group_id 하드코딩 절대 금지: prod 의 muscle_group id 는 uuid5(slug) 가 아니라
  다른 경로(seed + 20260603_dedup 통합)로 안착돼 로컬 계산값과 불일치한다. exercise_muscles
  가 이미 prod 실제 muscle id 를 참조하므로 JOIN-replay 만 환경 무관 정합 — STEP2 가
  자동으로 옳은 id 를 집는다.

안전성: equipment_muscles 는 순수 매핑테이블 → routine_exercises/workout_logs 등 사용자
  데이터와 무관(DELETE 해도 루틴/기록 손실 0). WHERE id IN 3개로 범위 한정(비파괴 원칙).
멱등: STEP1 DELETE 반복 무해, STEP2 ON CONFLICT DO NOTHING. clean DB 는 eqmuscle_direct 가
  이미 정답을 심었으므로 DELETE→동일 행 재INSERT(최종 상태 동일).
downgrade no-op: garbage 복구는 무의미 — equipment_muscles 정리는 PR-1 downgrade 가 담당.

후속(별도): 랫풀다운 보조근(biceps 등) 상류 보강, Assisted Dip/Chin 라벨 정합성,
  equipment_muscles 결손(arms 16/17 미매핑) 대규모 백필 — 본 교정 범위 밖.

asyncpg 안전: equipment id 는 리터럴 IN (chancegym_salus2 패턴). muscle id 는 JOIN 해석.
"""

from alembic import op

revision = "20260605_fix_arm_equipment_muscles"
down_revision = "20260605_recover_default_equip"
branch_labels = None
depends_on = None

# prod 실측으로 확정한 더찬스짐 의심 기구 3종 full UUID (결정론 seed 산출물 — 환경 동일).
_EQUIPMENT_IDS = [
    "bf3d0dde-84e3-510c-a43c-d0b017565431",  # 'Cable' (back, label=Machine Lat Pulldown)
    "e94bec5c-a634-58e9-872f-8f63eee2b625",  # 'Cable' (back, label=Machine Lat Pulldown)
    "2ca108c5-6153-5b7b-9b22-530ef902178c",  # 'Assisted Dip/Chin' (arms, label=Cable Triceps Pushdown)
]
_IDS_SQL = ", ".join(f"'{i}'" for i in _EQUIPMENT_IDS)


def upgrade() -> None:
    # STEP1) garbage 전량 DELETE — eqmuscle_direct ON CONFLICT DO NOTHING 우회 유일 방법.
    op.execute(f"DELETE FROM equipment_muscles WHERE equipment_id IN ({_IDS_SQL})")

    # STEP2) eqmuscle_direct JOIN replay (3개 id SCOPE). muscle_group_id 는 JOIN 으로 해석(하드코딩 금지).
    #        DELETE 선행이라 PK 충돌 없음 — ON CONFLICT 는 동시성 안전망.
    op.execute(
        f"""
        INSERT INTO equipment_muscles (equipment_id, muscle_group_id, involvement, activation_pct)
        SELECT DISTINCT ON (e.id, xm.muscle_group_id)
            e.id,
            xm.muscle_group_id,
            xm.involvement,
            xm.activation_pct
        FROM equipments e
        JOIN exercises ex ON lower(ex.name_en) = lower(e.movement_label_en)
        JOIN exercise_muscles xm ON xm.exercise_id = ex.id
        WHERE e.id IN ({_IDS_SQL})
          AND e.movement_label_en IS NOT NULL
        ORDER BY
            e.id,
            xm.muscle_group_id,
            (xm.involvement = 'primary') DESC,
            xm.activation_pct DESC NULLS LAST
        ON CONFLICT (equipment_id, muscle_group_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # no-op: garbage 복구 무의미. equipment_muscles 정리는 PR-1(equipment_centric_pr1) downgrade 소유.
    pass
