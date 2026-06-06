"""clean-slate reseed prep — 논문 제외 레퍼런스+루틴 초기화 + 운동-기구 재설계 스키마 변경

Revision ID: 20260606_clean_slate_reseed
Revises: 20260606_remap_default_equip
Create Date: 2026-06-06

⚠️⚠️ 파괴적 마이그('전체 wipe') — 적용 전 필수 체크리스트 (안전검증 verdict=SAFE) ⚠️⚠️
  1) 파괴적('전체 wipe'): exercises/equipments/muscle_groups + 루틴·프로그램 +
     workout_logs/workout_log_sets/user_exercise_1rm 전부 wipe (논문/users/chat/profile 보존). **사전 백업 필수**
     (현 백업: docs/handoff/db-export/*.csv — 실행 직전 타임스탬프 스냅샷 1회 더 권장).
  2) 모델/코드 동반 변경: ✅ 완료(Phase 2~4). default_equipment_id/equipment_muscles/movement_label_*/
     is_freeweight/exercise_equipment_map 참조가 코드에서 전부 제거됨(app.main import 검증). 본 마이그 단독
     적용해도 ORM 크래시 없음. 정합성 분리지점 = docs/handoff/2026-06-06-code-coupling-report.md.
  3) 적용 후 재시드 필수: 이 마이그는 빈 상태로 둠(INSERT 0건). 레퍼런스(exercises/equipments/muscle_groups/
     exercise_muscles)는 후속 시드 스크립트(mlops/scripts + db-export CSV)로 이 revision 뒤에 적재.

설계·안전검증: docs/spec/2026-06-06-exercise-equipment-workoutx-redesign.md §7,
  안전검증 verdict=SAFE (papers/paper_chunks 모델 대조 불가침 확인, FK 자식-우선 순서 정당, 멱등).

[논문 절대 불가침] papers / paper_chunks 에 대한 DELETE/DROP/ALTER 0건.
  papers를 참조하는 FK는 paper_chunks.paper_id(CASCADE)·routine_papers.paper_id(CASCADE) 둘뿐이고
  모두 child→papers 방향 → 자식 삭제는 papers 본체에 영향 없음. papers를 건드리지 않으므로
  CASCADE 트리거 자체가 발생 불가.
"""

import logging
import os

import sqlalchemy as sa
from alembic import op

revision = "20260606_clean_slate_reseed"
down_revision = "20260606_remap_default_equip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # 안전 가드: 논문 테이블은 절대 건드리지 않는다 (papers / paper_chunks).
    # 본 마이그는 papers/paper_chunks에 대한 어떠한 DELETE/DROP/ALTER도 수행하지 않는다.
    # =========================================================================

    # =========================================================================
    # 🔴 출시 후 사고 방지 가드 (pre-launch 자동 적용은 통과, 실데이터 wipe는 차단).
    #   이 마이그는 자동 배포 경로(deploy.yml → ECS `alembic upgrade head`)에서 실행된다.
    #   pre-launch(사용자 데이터 0행)에선 그대로 통과해 1회 재시드가 자동 완료되지만,
    #   출시 후(루틴/로그/1rm/프로그램 존재) 이 파괴적 전체 wipe가 다시 돌면 사용자 데이터를
    #   영구 삭제한다. 따라서 실데이터가 있으면 ALLOW_CLEAN_SLATE_WIPE 없이는 abort 한다.
    #   의도적 전체 초기화 시에만 백업 확보 후 ALLOW_CLEAN_SLATE_WIPE=1 로 재실행할 것.
    #   (alembic 단일 트랜잭션이라 abort=전체 ROLLBACK → 데이터 무손상.)
    # =========================================================================
    routine_cnt = conn.execute(sa.text("SELECT count(*) FROM workout_routines")).scalar_one()
    log_cnt = conn.execute(sa.text("SELECT count(*) FROM workout_logs")).scalar_one()
    set_cnt = conn.execute(sa.text("SELECT count(*) FROM workout_log_sets")).scalar_one()
    orm_cnt = conn.execute(sa.text("SELECT count(*) FROM user_exercise_1rm")).scalar_one()
    prog_cnt = conn.execute(sa.text("SELECT count(*) FROM programs")).scalar_one()
    user_data_total = routine_cnt + log_cnt + set_cnt + orm_cnt + prog_cnt

    allow_wipe = os.getenv("ALLOW_CLEAN_SLATE_WIPE", "").strip().lower() in ("1", "true", "yes")
    if user_data_total > 0 and not allow_wipe:
        raise RuntimeError(
            "clean_slate_reseed 안전중단: 사용자 데이터 존재("
            f"workout_routines={routine_cnt}, workout_logs={log_cnt}, "
            f"workout_log_sets={set_cnt}, user_exercise_1rm={orm_cnt}, programs={prog_cnt}). "
            "pre-launch가 아니므로 파괴적 전체 wipe를 자동 실행하지 않습니다. "
            "의도적 초기화라면 백업 확보 후 ALLOW_CLEAN_SLATE_WIPE=1 환경변수로 재실행하세요."
        )
    if user_data_total:
        logging.getLogger("alembic").warning(
            "clean-slate '전체 wipe'(ALLOW_CLEAN_SLATE_WIPE 승인): workout_routines=%s, workout_logs=%s, "
            "workout_log_sets=%s, user_exercise_1rm=%s, programs=%s 행 전량 삭제. 백업 확보 필수.",
            routine_cnt,
            log_cnt,
            set_cnt,
            orm_cnt,
            prog_cnt,
        )

    # =========================================================================
    # PHASE 1 — 데이터 wipe (FK 안전 순서). 논문/사용자(루틴 제외) 보존.
    #   RESTRICT blocker(routine_exercises→exercises/equipments,
    #   workout_log_sets→exercises, exercise_muscles→muscle_groups)를
    #   부모 삭제 전에 자식부터 비운다. eem / equipment_muscles 는 PHASE 2에서 DROP.
    # =========================================================================

    # 0) 프로그램 계열 (codex #2 fix): programs/program_routines 는 루틴에 종속된 사용자 구조라
    #    루틴 wipe 시 함께 정리한다. program_routines.routine_id→workout_routines 가 CASCADE라
    #    어차피 자동 삭제되지만, programs 빈 껍데기가 남지 않도록 명시 wipe (preserve 집합에서 제외).
    op.execute("DELETE FROM program_routines")
    op.execute("DELETE FROM programs")

    # 1) 루틴 계열 (사용자 데이터 중 '루틴 도메인' wipe).
    #    routine_papers는 papers.id를 CASCADE 참조하나 routine_id 방향으로만 삭제 →
    #    papers 본체 무손상.
    op.execute("DELETE FROM routine_papers")
    op.execute("DELETE FROM routine_exercises")
    op.execute("DELETE FROM routine_days")
    op.execute("DELETE FROM workout_routines")

    # 2) 운동 기록 '전체 wipe'. workout_log_sets→workout_logs(CASCADE) +
    #    workout_log_sets→exercises(RESTRICT)라 set 먼저 → log 헤더 → 1rm 순(모두 exercises 앞).
    op.execute("DELETE FROM workout_log_sets")
    op.execute("DELETE FROM workout_logs")
    op.execute("DELETE FROM user_exercise_1rm")

    # 3) muscle_groups RESTRICT 자식 선비움 (exercise_muscles).
    #    equipment_muscles는 PHASE 2에서 테이블째 DROP되어 RESTRICT가 해소된다.
    op.execute("DELETE FROM exercise_muscles")

    # 4) equipments CASCADE 자식 + gym 조인 정션 선비움 (gyms 보존).
    op.execute("DELETE FROM gym_equipments")
    op.execute("DELETE FROM equipment_reports")
    op.execute("DELETE FROM equipment_suggestions")

    # =========================================================================
    # PHASE 2 — 스키마 변경 (멱등 IF EXISTS / IF NOT EXISTS).
    #   eem · equipment_muscles DROP을 이 시점에 수행하면 잔존 데이터까지 함께 제거되고
    #   muscle_groups RESTRICT(equipment_muscles발) 도 해소된다.
    # =========================================================================

    # 2a) exercises.load_mode 추가 (nullable; 재시드가 채움).
    op.execute("ALTER TABLE exercises ADD COLUMN IF NOT EXISTS load_mode varchar(20)")

    # 2b) exercises.default_equipment_id 제거 (컬럼+FK). equipments wipe 차단 해소.
    op.execute("ALTER TABLE exercises DROP COLUMN IF EXISTS default_equipment_id")

    # 2c) exercise_equipment 신규 정션 (머신 운동만 행 보유 — 재시드가 채움).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS exercise_equipment (
            exercise_id  uuid NOT NULL REFERENCES exercises (id) ON DELETE CASCADE,
            equipment_id uuid NOT NULL REFERENCES equipments (id) ON DELETE CASCADE,
            source       varchar(20) NOT NULL DEFAULT 'seed',
            confidence   numeric(3,2) NULL,
            PRIMARY KEY (exercise_id, equipment_id)
        )
        """
    )

    # 2d) 폐기 테이블 DROP (= 데이터 wipe). CASCADE로 의존 FK/제약 함께 제거.
    op.execute("DROP TABLE IF EXISTS exercise_equipment_map CASCADE")
    op.execute("DROP TABLE IF EXISTS equipment_muscles CASCADE")

    # 2e) equipments 폐기 컬럼 제거.
    op.execute("ALTER TABLE equipments DROP COLUMN IF EXISTS is_freeweight")  # GENERATED STORED
    op.execute("ALTER TABLE equipments DROP COLUMN IF EXISTS movement_label_en")
    op.execute("ALTER TABLE equipments DROP COLUMN IF EXISTS movement_label_ko")

    # 2f) routine_exercises.equipment_id NULL 허용 (프리웨이트=NULL). RESTRICT FK는 유지.
    op.execute("ALTER TABLE routine_exercises ALTER COLUMN equipment_id DROP NOT NULL")

    # =========================================================================
    # PHASE 3 — 레퍼런스 부모 wipe.
    #   default_equipment_id(FK) 제거 완료 → equipments 삭제 차단 없음.
    #   exercises RESTRICT 자식(routine_exercises/log_sets/exercise_muscles/1rm) 모두 선비움 완료.
    # =========================================================================
    op.execute("DELETE FROM equipments")
    op.execute("DELETE FROM exercises")
    op.execute("DELETE FROM muscle_groups")

    # 재시드(WorkoutX 기준)는 후속 시드 마이그/스크립트가 빈 상태에서 적재한다.


def downgrade() -> None:
    # forward-only: 클린슬레이트는 비가역(wipe된 레퍼런스/루틴/스키마 복원 불가).
    # 롤백이 필요하면 마이그 전 백업(db-export 스냅샷)에서 복구할 것.
    raise RuntimeError(
        "clean_slate_reseed 는 비가역 마이그레이션입니다. 롤백하려면 적용 전 백업에서 복구하세요(downgrade 미지원)."
    )
