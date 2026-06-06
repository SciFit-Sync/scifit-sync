"""freeweight default_equipment_id 오배정 정정 (EZ Bar / Assisted Pull-up garbage 허브 드레이닝)

Revision ID: 20260606_remap_default_equip
Revises: 20260605_dipchin_compound
Create Date: 2026-06-06

배경 (오배정 발생):
  exercises.default_equipment_id 백필(20260604_ex_default_equip / 20260605_recover_default_equip)이
  eem의 freeweight 기구를 `DISTINCT ON(exercise_id) ... ORDER BY equipment_type, e.id` 로 골랐다.
  tie-break가 type별 '최소 UUID'를 선택했고, eem 26,102행 과매핑 탓에 그 최소 UUID가 하필
  특수/보조 기구였다:
    - EZ Bar (barbell, bar_weight=10)         → 177개 운동의 default 로 흡수
    - Assisted Pull-up Machine (assist=true)  → 376개 운동의 default 로 흡수
  결과: 맨몸 운동이 assist 머신에 묶여 load_calc 가 `body_weight − stack`(음수/garbage) 분기로,
        바벨 컴파운드가 EZ Bar(10kg)에 묶여 bar 10kg 과소 계산. (전수감사 547건, real_mislink 515)

판정 근거(런타임):
  프리웨이트 운동의 default_equipment_id → 루틴 생성 시 routine_exercises.equipment_id 로 복사되고
  load_calc.calculate_effective_weight 가 그 기구의 equipment_type / bar_weight / has_weight_assist 로
  실효중량을 계산한다. 머신/케이블 운동은 default 를 두지 않는다(movement_label_en==name_en 경로).

해결 (이 마이그레이션, UPDATE only / forward-only / 멱등):
  garbage 허브(EZ Bar·Assisted)에 묶인 행만 좁혀 hub-aware 재산정한다. '현재 어느 허브냐'가
  운동 계열을 알려준다 — EZ 허브=바벨 계열, Assisted 허브=맨몸 계열. 이름 키워드로 예외만 덮어쓴다.
    STEP A: 허브 묶인 553개 → 머신명=NULL / 덤벨명=Dumbbell / EZ명=EZ유지 /
            EZ허브 잔여=Barbell(20kg) / Assisted허브 잔여=(바벨명 Barbell, 그외 Bodyweight)
    STEP B: default 없는데 dumbbell/ez/barbell '명시' 운동만 보수적 백필.
  prod 실데이터 시뮬 검증: STEP A 532건 변경(Bodyweight 373 / Barbell 154 / NULL 5), EZ유지 21.

  정본 generic(name_en 룩업 — 환경 간 UUID 드리프트 차단, seed/uuid5 결정론):
    Barbell  (name_en='Barbell',  name='Barbell',  barbell, bar=20)  — equipments_seed.csv
    Dumbbell (name_en='Dumbbell', name='Dumbbell', dumbbell)         — equipments_seed.csv
    Bodyweight (name_en='Bodyweight', name='맨몸',  bodyweight, assist=false) — uuid5(20260604_bodyweight_seed)
  EZ Bar / Assisted '6eff9e86' 류 v4 중복 dumbbell·Smith 타입오류·중복기구 dedup 은
  DELETE/ALTER 가 얽혀 blast 가 크므로 본 마이그 범위 밖(별도 후속 PR, 백업+허가).

이식성: garbage 허브 미존재 env(CI clean 등)는 STEP A 대상 0 → no-op. canon 누락 시 RAISE 로 전체 롤백.
asyncpg: 정적 SQL(DO 블록)이라 named param 불요. downgrade 는 비가역(원본 garbage 매핑은 결함이라 복원가치 0).
"""

from alembic import op

revision = "20260606_remap_default_equip"
down_revision = "20260605_dipchin_compound"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        DO $$
        DECLARE
            ez_bar     uuid;
            assist     uuid;
            c_barbell  uuid;
            c_dumbbell uuid;
            c_bodywt   uuid;
        BEGIN
            -- garbage 허브 (name 룩업; 미존재 env 는 NULL → STEP A 대상 0)
            --   canon 만큼 엄격한 술어로 고정(EZ=bar 10kg, Assisted=bodyweight+assist) → drift env 오타겟 차단
            SELECT id INTO ez_bar FROM equipments
                WHERE name_en = 'EZ Bar' AND equipment_type = 'barbell' AND bar_weight = 10
                ORDER BY id LIMIT 1;
            SELECT id INTO assist FROM equipments
                WHERE name_en = 'Assisted Pull-up Machine' AND equipment_type = 'bodyweight'
                  AND has_weight_assist = true ORDER BY id LIMIT 1;

            -- 정본 generic (재배정 타깃; v5 결정론 generic 만 잡도록 name+name_en+type 동시 조건)
            SELECT id INTO c_barbell  FROM equipments
                WHERE name_en = 'Barbell'  AND name = 'Barbell'  AND equipment_type = 'barbell'
                  AND bar_weight = 20 ORDER BY id LIMIT 1;
            SELECT id INTO c_dumbbell FROM equipments
                WHERE name_en = 'Dumbbell' AND name = 'Dumbbell' AND equipment_type = 'dumbbell'
                ORDER BY id LIMIT 1;
            SELECT id INTO c_bodywt   FROM equipments
                WHERE name_en = 'Bodyweight' AND name = '맨몸' AND equipment_type = 'bodyweight'
                  AND has_weight_assist = false ORDER BY id LIMIT 1;

            -- 고칠 게 있는데(허브 존재) 타깃 generic 이 없으면 부분적용 금지 → 전체 롤백
            IF (ez_bar IS NOT NULL OR assist IS NOT NULL)
               AND (c_barbell IS NULL OR c_dumbbell IS NULL OR c_bodywt IS NULL) THEN
                RAISE EXCEPTION
                    'canonical generic missing (barbell=%, dumbbell=%, bodyweight=%) — abort remap',
                    c_barbell, c_dumbbell, c_bodywt;
            END IF;

            -- ── STEP A: garbage 허브 묶인 운동 hub-aware 재산정 ──────────────────────
            --   CASE 우선순위(위→아래 첫 매칭): 머신 → 덤벨 → EZ유지 → EZ허브바벨 → Assisted허브
            UPDATE exercises e
            SET default_equipment_id = CASE
                -- (1) 머신/케이블/스미스/treadmill/lever-머신/hack-머신 → NULL
                WHEN e.name_en ~* '(smith|sled|pendulum|leverage|machine)'
                  OR e.name_en ~* '\ycable\y'
                  OR e.name_en ~* '(treadmill|elliptical|air bike)'
                  OR e.name_en ~* 'run \(equipment\)'
                  OR (e.name_en ~* '\ylever\y'
                      AND e.name_en !~* '(front lever|back lever|lever hold|planche|human flag)')
                  OR (e.name_en ~* 'hack squat' AND e.name_en !~* '\ybarbell\y')
                    THEN NULL
                -- (2) 진짜 어시스트-머신 운동(assisted, 단 self/band 제외) → 현 Assisted 머신 유지
                --     어시스트 풀업/친업/딥은 load_calc 의 body_weight − stack 가 오히려 정확하므로 건드리지 않는다.
                --     ('Self/Band Assisted' 는 머신이 아니라 맨몸/밴드 → 아래 ELSE 로 떨어져 Bodyweight)
                --     prod 실데이터에선 매칭 0(해당 운동 전부 default NULL) — 타 env 포터빌리티용 방어가드.
                WHEN e.name_en ~* '\yassisted\y' AND e.name_en !~* '\y(self|band)\y' THEN assist
                -- (3) 덤벨 명시 → 정본 Dumbbell
                WHEN e.name_en ~* '\ydumbbell\y' THEN c_dumbbell
                -- (4) EZ 명시 isolation → EZ Bar 유지 (10kg 가 컬에 물리적으로 적합)
                WHEN e.name_en ~* '\yez[ -]?(bar|barbell)?\y' THEN ez_bar
                -- (5) EZ 허브(=바벨 계열) 잔여 → 정본 Barbell(20kg)
                WHEN e.default_equipment_id = ez_bar THEN c_barbell
                -- (6) Assisted 허브(=맨몸 계열): 바벨 명시만 Barbell, 그 외 Bodyweight
                WHEN e.name_en ~* '\ybarbell\y' THEN c_barbell
                ELSE c_bodywt
            END
            WHERE e.default_equipment_id IN (ez_bar, assist);

            -- ── STEP B: default 없는데 dumbbell/ez/barbell '명시' 운동만 보수적 백필 ──
            --   머신명 제외(NOT 가드). 맨몸 이름(키워드 없음)은 모호성 커서 미백필(현상유지).
            UPDATE exercises e
            SET default_equipment_id = CASE
                WHEN e.name_en ~* '\ydumbbell\y' THEN c_dumbbell
                WHEN e.name_en ~* '\yez[ -]?(bar|barbell)?\y' THEN ez_bar
                WHEN e.name_en ~* '\ybarbell\y' THEN c_barbell
            END
            WHERE e.default_equipment_id IS NULL
              AND ( e.name_en ~* '\ydumbbell\y'
                 OR e.name_en ~* '\yez[ -]?(bar|barbell)?\y'
                 OR e.name_en ~* '\ybarbell\y' )
              AND NOT ( e.name_en ~* '(smith|sled|pendulum|leverage|machine)'
                     OR e.name_en ~* '\ycable\y'
                     OR (e.name_en ~* '\ylever\y'
                         AND e.name_en !~* '(front lever|back lever|lever hold|planche|human flag)')
                     OR (e.name_en ~* 'hack squat' AND e.name_en !~* '\ybarbell\y') );

            RAISE NOTICE 'remap done: garbage-hub remaining default_for(EZ=%, Assisted=%)',
                (SELECT count(*) FROM exercises WHERE default_equipment_id = ez_bar),
                (SELECT count(*) FROM exercises WHERE default_equipment_id = assist);
        END $$;
        """
    )


def downgrade() -> None:
    # forward-only: 원본 garbage 매핑(EZ Bar/Assisted 일괄)은 결함 상태라 복원 가치가 없다.
    # 롤백이 필요하면 마이그 적용 전 exercises(id, default_equipment_id) 스냅샷으로 되돌린다.
    pass
