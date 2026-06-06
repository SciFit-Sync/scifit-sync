# Prod Reseed Runbook — clean_slate_reseed + WorkoutX 재시드 (2026-06-06)

> 대상 DB: Supabase **hnwegx** (prod). `server/.env DATABASE_URL`은 빈 dev junpxp이므로 반드시 prod URL로 덮어쓸 것.
> 이 문서는 단계별 실행 명령과 검증 SQL을 포함한다. 되돌리기(downgrade)는 미지원이므로 사전 백업이 유일한 롤백 수단.

---

## 사전 체크리스트 (실행 전 반드시 확인)

- [ ] ECS Task count = 1 확인 (ChromaDB 동시 쓰기 금지, 멀티 태스크 절대 금지)
- [ ] 현재 브랜치 = `fix/jingyu/default-equipment-remap` (또는 clean_slate_reseed 마이그가 포함된 브랜치)
- [ ] `server/alembic/versions/20260606_clean_slate_reseed.py` 존재 확인
- [ ] `mlops/scripts/seed_reference_data.py` 존재 확인
- [ ] `mlops/scripts/seed_exercises_workoutx.py` 존재 확인 (Phase 1 재작성 버전)
- [ ] db-export CSV 3종 존재 확인:
  - `docs/handoff/db-export/equipment_brands.csv` (14 brands + header = 15줄)
  - `docs/handoff/db-export/equipments.csv` (132 rows + header = 133줄)
  - `docs/handoff/db-export/gym_equipments.csv` (33 rows + header = 34줄)
- [ ] `docs/handoff/workoutx-raw/exercises.json` 존재 (1324 운동, 라이브 재호출 금지)

---

## Step 0 — 사전 백업 (필수)

### 0a. db-export 타임스탬프 스냅샷

현재 db-export는 2026-06-05 기준이나, 실행 직전 prod 스냅샷을 추가로 확보한다.

```bash
# prod DB의 현재 행수를 기록 (asyncpg + prod DATABASE_URL 필요)
# 아래 명령은 psql 또는 Supabase SQL Editor에서 실행 가능
SELECT
  'papers'        AS tbl, count(*) FROM papers
UNION ALL SELECT 'paper_chunks',  count(*) FROM paper_chunks
UNION ALL SELECT 'exercises',     count(*) FROM exercises
UNION ALL SELECT 'muscle_groups', count(*) FROM muscle_groups
UNION ALL SELECT 'equipments',    count(*) FROM equipments
UNION ALL SELECT 'gym_equipments',count(*) FROM gym_equipments
UNION ALL SELECT 'workout_logs',  count(*) FROM workout_logs
UNION ALL SELECT 'workout_log_sets', count(*) FROM workout_log_sets;
```

> papers / paper_chunks 행수를 반드시 메모해 둔다. 재시드 후 이 숫자가 변하면 즉시 중단.

### 0b. 기존 exercises / equipments 백업 (이미 db-export에 있으면 생략 가능)

```bash
# Supabase SQL Editor → "Download CSV" 또는 아래 명령
# 이미 docs/handoff/db-export/*.csv 가 최신이라면 별도 작업 불필요
```

---

## Step 1 — DATABASE_URL 설정 (prod, service role)

`server/.env` 의 `DATABASE_URL`을 prod Supabase hnwegx **service role** connection string으로 교체한다.

```bash
# server/.env 편집 — asyncpg 드라이버 필수
# 형식: postgresql+asyncpg://postgres.[project-ref]:[password]@[host]:5432/postgres
# Supabase > Settings > Database > Connection string (URI) 에서 확인
# ⚠️ 이 파일은 절대 커밋하지 않는다 (.gitignore 확인)
```

> PgBouncer(pooler) 사용 시 `?statement_cache_size=0` 쿼리스트링 추가 필수 (asyncpg 호환).
> 예: `postgresql+asyncpg://...@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres?statement_cache_size=0`

---

## Step 2 — alembic upgrade head (clean_slate_reseed 적용)

```bash
cd /path/to/scifit-sync/server

# 현재 revision 확인
alembic current

# clean_slate_reseed 포함 여부 확인 (20260606_clean_slate_reseed 가 pending이어야 함)
alembic history --verbose | head -20

# 실행 — 전체 wipe 발생. 되돌리기 불가.
alembic upgrade head
```

**이 마이그레이션이 수행하는 작업 (비가역):**
1. `program_routines`, `programs` 삭제
2. `routine_papers`, `routine_exercises`, `routine_days`, `workout_routines` 삭제
3. `workout_log_sets`, `workout_logs`, `user_exercise_1rm` 삭제
4. `exercise_muscles` 삭제
5. `gym_equipments`, `equipment_reports`, `equipment_suggestions` 삭제
6. 스키마 변경: `exercises.load_mode` 추가, `default_equipment_id` 제거, `exercise_equipment` 정션 생성, `exercise_equipment_map` / `equipment_muscles` DROP
7. `equipments`, `exercises`, `muscle_groups` 전량 삭제

**논문 절대 불가침**: `papers` / `paper_chunks` 에 대한 DELETE/DROP/ALTER 0건.

> 실행 중 alembic warning 로그:
> `clean-slate '전체 wipe': workout_logs=N, ...` — 이는 정상 경고. 계속 진행.

---

## Step 3 — 재시드 실행

### 3a. seed_reference_data.py — muscle_groups + equipments + brands + gym_equipments

```bash
cd /path/to/scifit-sync

# DATABASE_URL 이 server/.env 에 prod로 설정됐는지 재확인
python mlops/scripts/seed_reference_data.py
```

**기대 출력 (대략):**
```
muscle_groups upsert 완료: 20건
equipment_brands upsert 완료: 14건
equipments upsert 완료: 132건
gym_equipments upsert 완료: 33건
완료
```

> 멱등 스크립트 (`on_conflict_do_update`). 실패 시 재실행 가능.

### 3b. seed_exercises_workoutx.py — exercises + exercise_muscles

```bash
cd /path/to/scifit-sync

# WORKOUTX_API_KEY 환경변수 불필요: frozen JSON 소스 사용
# DATABASE_URL 이 prod로 설정됐는지 재확인
python mlops/scripts/seed_exercises_workoutx.py
```

**기대 출력 (대략):**
```
exercises.json 소스 로드: 1324건 → dedup 후 1318건 (6건 keep-last)
exercises upsert 완료: 1318건
exercise_muscles (primary) 적재: 1318건
exercise_muscles (secondary) 적재: ~2000건
load_mode NULL (cardio 제외): 0건
완료
```

**스크립트 내부 동작 (Phase 1 재작성 기준):**
- 소스: `docs/handoff/workoutx-raw/exercises.json` (라이브 API 미호출, 변동 차단)
- `name_en` 중복 6건 사전 dedup (keep-last):
  - Barbell Seated Calf Raise
  - Ez Barbell Spider Curl
  - Lever Chest Press
  - Push-up (on Stability Ball)
  - Self Assisted Inverse Leg Curl
  - Smith Reverse Calf Raises
- `exercises.category` = `bodyPart` 원문 그대로 (Back/Cardio/Chest/Lower Arms/Lower Legs/Neck/Shoulders/Upper Arms/Upper Legs/Waist)
- `load_mode` 매핑 (11종 + cardio + skip):

  | WorkoutX equipment | load_mode |
  |---|---|
  | Barbell, Olympic Barbell | barbell |
  | Ez Barbell, Ez Barbell + Exercise Ball | ez_barbell |
  | Trap Bar | trap_bar |
  | Dumbbell, Dumbbell variants | dumbbell |
  | Body Weight, Body Weight (with Resistance Band) | bodyweight |
  | Weighted | weighted |
  | Kettlebell | kettlebell |
  | Band, Resistance Band, Rope | band |
  | Cable | cable |
  | Leverage Machine, Smith Machine, Assisted, Assisted (towel), Sled Machine, Hammer, Tire | machine |
  | Elliptical Machine, Skierg Machine, Stationary Bike, Stepmill Machine, Upper Body Ergometer | cardio |
  | Stability Ball, Bosu Ball, Roller, Wheel Roller, Medicine Ball, Rope | bodyweight |

  > exercises.json 34종 equipment 값 전수 매핑 완료 (missing 0건). 맵에 없는 신규 값은 `ValueError` fail-fast — 데이터 진화 시 즉시 발견.
  > skip되는 운동은 0건. bodyPart 없는 행만 경고 후 skip.

- `muscle_groups` assert: 적재 전 20 canon이 DB에 존재하는지 검증. 없으면 즉시 abort.
- `exercise_muscles`:
  - target → involvement='primary' (정규화 없음, target은 이미 canon)
  - secondaryMuscles → `_SECONDARY_TO_CANON` 맵으로 정규화 후 involvement='secondary'
  - 정규화 후 primary와 secondary canon이 동일하면 secondary 무시 (primary 우선)
  - DROP 5종 제외: Ankles, Feet, Ankle Stabilizers, Hands, Shins
  - `activation_pct` = NULL (seed_activation_pct.py 후속 백필)
- `exercise_equipment` 정션은 **이번 스크립트에서 채우지 않음** (Phase 7 Gemini 검증 전용)

---

## Step 4 — 검증 SQL

아래 SQL을 Supabase SQL Editor에서 실행해 모두 PASS인지 확인.

### 4a. papers / paper_chunks 불변 확인 (가장 중요)

```sql
-- Step 0에서 기록한 숫자와 일치해야 함
SELECT count(*) AS papers_count    FROM papers;
SELECT count(*) AS chunks_count    FROM paper_chunks;
```

> 숫자가 다르면 즉시 중단하고 백업 복구.

### 4b. muscle_groups 20 canon 확인

```sql
SELECT count(*) FROM muscle_groups;
-- 기대: 20

SELECT name FROM muscle_groups ORDER BY name;
-- 기대: Abs, Adductors, Abductors, Biceps, Calves, Cardiovascular System,
--        Delts, Forearms, Glutes, Hamstrings, Hip Flexors, Lats,
--        Levator Scapulae, Pectorals, Quads, Serratus Anterior,
--        Spine, Traps, Triceps, Upper Back
```

### 4c. exercises load_mode NULL 0건 (cardio 제외)

```sql
SELECT count(*) AS null_load_mode_non_cardio
FROM exercises
WHERE load_mode IS NULL
  AND category != 'Cardio';
-- 기대: 0
```

### 4d. exercise_muscles primary 결손 0건

```sql
-- primary가 없는 운동 = 재시드 누락
SELECT count(*) AS missing_primary
FROM exercises e
WHERE NOT EXISTS (
  SELECT 1 FROM exercise_muscles em
  WHERE em.exercise_id = e.id AND em.involvement = 'primary'
);
-- 기대: 0 (cardio 운동 포함 전체)
```

### 4e. exercise_muscles orphan 0건

```sql
-- muscle_group_id 참조가 없는 행
SELECT count(*) AS orphan_muscles
FROM exercise_muscles em
WHERE NOT EXISTS (
  SELECT 1 FROM muscle_groups mg WHERE mg.id = em.muscle_group_id
);
-- 기대: 0
```

### 4f. gym_equipments orphan 0건

```sql
SELECT count(*) AS orphan_gym_eq
FROM gym_equipments ge
WHERE NOT EXISTS (
  SELECT 1 FROM equipments eq WHERE eq.id = ge.equipment_id
);
-- 기대: 0
```

### 4g. exercises 총 건수 확인

```sql
SELECT count(*) FROM exercises;
-- 기대: 1318 (1324 - 6 dedup)
```

### 4h. exercise_equipment 정션 비어있음 확인 (Phase 7 전)

```sql
SELECT count(*) FROM exercise_equipment;
-- 기대: 0 (Phase 7 Gemini 검증 후 채워질 예정)
```

---

## 롤백 절차 (비상시)

`clean_slate_reseed`는 `downgrade()`가 `RuntimeError`를 raise하므로 alembic downgrade 불가.

**유일한 롤백 수단**: Step 0에서 확보한 백업에서 수동 복구.

```bash
# 방법 1: Supabase Point-in-Time Recovery (PITR) — 콘솔에서 복원 요청
# 방법 2: db-export CSV를 수동 INSERT (exercises/equipments/muscle_groups 순서)
# 방법 3: Supabase 콘솔 > Database > Backups 에서 특정 시점 복원
```

> 현재 prod는 pre-launch 상태 (`workout_routines` 0건)이므로 롤백 영향 범위 = 레퍼런스 데이터만.

---

## 가드레일 및 주의사항

### papers / paper_chunks 절대 불가침
- 마이그레이션 코드에서 `papers` / `paper_chunks`에 대한 DELETE/DROP/ALTER 는 **0건**임이 코드 리뷰에서 확인됨.
- 검증 Step 4a 에서 행수 불변을 반드시 확인할 것.

### ECS Task count = 1 유지
- ChromaDB PersistentClient는 단일 프로세스 전용. 재시드 중 ECS 태스크가 2개 이상이면 ChromaDB 데이터 손상 가능.
- `aws ecs describe-services` 또는 ECS 콘솔에서 Running task count = 1 확인.

### Phase 7 exercise_equipment 정션 미적용 시 머신 운동 가용성 0
- `exercise_equipment` 정션이 비어있으면 헬스장 기구 기반 루틴 생성 시 **머신/케이블 운동이 0건** 매칭됨.
- 루틴 생성 API는 프리웨이트(load_mode IN (barbell/dumbbell/bodyweight/...)) 운동은 정션 없이도 사용 가능.
- Phase 7(Gemini 검증 산출물)이 준비되기 전까지는 **프리웨이트 루틴 생성만 가능**한 상태임을 팀에 공유.

### Alembic 단독 관리
- Supabase 대시보드 직접 스키마 수정 절대 금지.
- 모든 스키마 변경은 `server/alembic/versions/` 마이그레이션 파일을 통해서만.

### seed_activation_pct.py 후속 실행
- `exercise_muscles.activation_pct` 는 재시드 직후 전부 NULL.
- `mlops/scripts/seed_activation_pct.py` 를 재시드 후 별도 실행해야 함 (Phase 후속 작업).

---

## 실행 순서 요약

```
Step 0: 사전 백업 (papers/paper_chunks 행수 기록 + db-export 스냅샷)
   ↓
Step 1: server/.env → prod DATABASE_URL 설정
   ↓
Step 2: alembic upgrade head  (clean_slate_reseed 적용 — 전체 wipe + 스키마 변경)
   ↓
Step 3a: python mlops/scripts/seed_reference_data.py
         (muscle_groups 20 + equipment_brands 14 + equipments 132 + gym_equipments 33)
   ↓
Step 3b: python mlops/scripts/seed_exercises_workoutx.py
         (exercises 1318 + exercise_muscles ~3000)
   ↓
Step 4: 검증 SQL (4a~4h 전부 PASS 확인)
   ↓
   ✓ 완료
```

---

## 관련 파일

| 파일 | 역할 |
|---|---|
| `server/alembic/versions/20260606_clean_slate_reseed.py` | 전체 wipe + 스키마 변경 마이그레이션 |
| `server/alembic/versions/20260606_remap_default_equipment.py` | 직전 마이그 (down_revision) |
| `mlops/scripts/seed_reference_data.py` | muscle_groups + 기구 CSV 적재 |
| `mlops/scripts/seed_exercises_workoutx.py` | exercises + exercise_muscles 적재 (Phase 1 재작성) |
| `docs/handoff/workoutx-raw/exercises.json` | 동결 소스 1324건 |
| `docs/handoff/workoutx-raw/muscle_normalization.md` | 35행 정규화 맵 + DROP 5종 |
| `docs/handoff/workoutx-raw/freeweight_load_modes.csv` | load_mode 11종 baseline |
| `docs/handoff/db-export/equipments.csv` | 기구 132행 |
| `docs/handoff/db-export/equipment_brands.csv` | 브랜드 14행 |
| `docs/handoff/db-export/gym_equipments.csv` | 헬스장↔기구 33행 |
