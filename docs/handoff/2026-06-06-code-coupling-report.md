# 코드 정합성 분리지점 보고서 — 운동-기구 재설계(WorkoutX)

> 작성 2026-06-06 · ultracode 워크플로(8 서브시스템 fan-out → 적대 검증, 18 에이전트) 산출
> 대상: docs/spec/2026-06-06-exercise-equipment-workoutx-redesign.md 의 스키마 변경으로 깨지는 코드 전수
> 마이그 draft: docs/handoff/migrations-draft/20260606_clean_slate_reseed.py

## 0. 요약 — 총 142건 (중복제거 후)

| severity | 건수 |
|---|---|
| critical | 84 |
| high | 45 |
| medium | 13 |

**레이어별:**

| 레이어 | 건수 |
|---|---|
| API | 75 |
| 모델(ORM) | 32 |
| 테스트 | 12 |
| 서비스 | 11 |
| MLOps/시드 | 6 |
| 스키마(Pydantic) | 4 |
| 기타 | 2 |

**파일별 (영향 큰 순):**

| 파일 | 건수 |
|---|---|
| `routines.py` | 50 |
| `gyms.py` | 15 |
| `gym.py` | 14 |
| `exercise.py` | 12 |
| `test_routine_equipment_rag.py` | 8 |
| `admin.py` | 5 |
| `load_calc.py` | 5 |
| `equipment.py` | 4 |
| `rag.py` | 4 |
| `__init__.py` | 3 |
| `routine.py` | 3 |
| `exercises.py` | 2 |
| `routine_targets.py` | 2 |
| `seed.py` | 2 |
| `sessions.py` | 2 |
| `test_gym_muscle_equipments.py` | 2 |
| `test_routines.py` | 2 |
| `20260604_equipment_centric_pr1.py` | 1 |
| `20260604_seed_freeweight_exercises.py` | 1 |
| `20260604_seed_machine_movement_templates.py` | 1 |
| `20260605_eqmuscle_deficit_backfill.py` | 1 |
| `gen_freeweight_seed.py` | 1 |
| `seed_exercises_workoutx.py` | 1 |
| `users.py` | 1 |

---

## 1. 파일별 상세

### `routines.py` (50)
- 🔴 **Line 922 local import statement** — 의존: `EquipmentMuscle model import inside _build_rag_profile (deprecated)`
  - 깨짐: Line 922: from app.models.gym import EquipmentMuscle. Model deleted post-migration. Import fails, entire _build_rag_profile function cannot execute.
  - 수정: Remove EquipmentMuscle local import. Rewrite machine filtering to use exercise_equipment -> exercise_muscles path.
- 🔴 **Lines 935-970 _build_rag_profile, machine_stmt query** — 의존: `Equipment.is_freeweight filter, Equipment.movement_label_en ORDER BY, EquipmentMuscle JOIN`
  - 깨짐: Line 947: WHERE Equipment.is_freeweight==False will fail (column dropped). Line 955: ORDER BY Equipment.movement_label_en will fail (column dropped). Line 951: JOIN EquipmentMuscle will fail (table dropped). No machine candidates returned, routine generation fails.
  - 수정: Remove is_freeweight filter. Replace movement_label_en ORDER BY with Equipment.name. Replace EquipmentMuscle JOIN with exercise_equipment -> exercise_muscles path.
- 🔴 **Lines 972-992 _build_rag_profile, free_stmt query** — 의존: `Exercise.default_equipment_id JOIN, Equipment.is_freeweight filter`
  - 깨짐: Line 981: JOIN Equipment on Exercise.default_equipment_id FK will fail (column dropped). Line 984: WHERE Equipment.is_freeweight==True will fail (column dropped). No freeweight candidates returned.
  - 수정: Remove default_equipment_id JOIN. Replace with Exercise.load_mode IN ('barbell','ez_barbell',...) filter.
- 🔴 **Lines 1020-1057 _build_rag_profile, fallback free_stmt** — 의존: `Exercise.default_equipment_id JOIN, Equipment.is_freeweight filter (when gym_id is None)`
  - 깨짐: Line 1029: JOIN on Exercise.default_equipment_id will fail. Line 1032: WHERE Equipment.is_freeweight==True will fail. Fallback query fails when no gym specified, entire routine generation fails.
  - 수정: Replace with Exercise.load_mode IN (...) filter and remove default_equipment_id JOIN.
- 🔴 **Lines 1236-1271 _pick_equipment_for_exercise function** — 의존: `Exercise.default_equipment_id field, Equipment.movement_label_en matching`
  - 깨짐: Line 1257: returns Exercise.default_equipment_id (field dropped). Line 1263: WHERE lower(Equipment.movement_label_en)==label_lc will fail (column dropped). Equipment selection for exercise substitution fails, PATCH /routines/{id}/exercises/{exId} returns 409 ConflictError.
  - 수정: Rewrite with load_mode branching: freeweight -> no equipment (NULL), machine -> exercise_equipment junction query.
- 🔴 **Lines 450-464 update_routine_exercise function, line 460 _pick_equipment_for_exercise call** — 의존: `Exercise.default_equipment_id and Equipment.movement_label_en used by _pick_equipment_for_exercise (lines 1236-1271)`
  - 깨짐: Line 460 calls _pick_equipment_for_exercise() for auto-selection when user changes exercise but not equipment in PATCH. _pick_equipment_for_exercise depends on default_equipment_id and movement_label_en fields. Both will be dropped. Equipment auto-selection fails, returns None, raises 409 ConflictError.
  - 수정: Rewrite _pick_equipment_for_exercise with load_mode branching before calling at line 460.
- 🔴 **lines 935-969 (_build_rag_profile machine_stmt query)** — 의존: `Equipment.is_freeweight (GENERATED column)`
  - 깨짐: Line 947: WHERE Equipment.is_freeweight == False를 사용한 머신 필터링. 모델에서는 is_freeweight가 GENERATED STORED 컬럼으로 실제 존재(gym.py:136-139)하지만, 스펙에서 제거되면 쿼리 실패.
  - 수정: equipment_type IN ('cable', 'machine') 조건으로 변경. equipment_type enum(EquipmentType)을 기준으로 머신 분류.
- 🔴 **line 939-941, 955, 959 (SELECT Equipment.movement_label_en)** — 의존: `Equipment.movement_label_en (컬럼)`
  - 깨짐: 라인 939에서 SELECT Equipment.movement_label_en, 955에서 ORDER BY movement_label_en, 959에서 label = row.movement_label_en 사용. 모델에서는 컬럼 존재(gym.py:135)하지만, 스펙에서 제거되면 쿼리/속성 접근 실패.
  - 수정: movement_label_en을 Exercise.name_en으로 대체. machine_stmt ORDER BY를 Equipment.name_en으로 변경, label 구성 로직을 row.name_en or row.name으로 단순화.
- 🔴 **lines 950-954 (machine_stmt with EquipmentMuscle JOIN)** — 의존: `EquipmentMuscle 테이블 + JOIN 구문`
  - 깨짐: 라인 951-953: machine_stmt.join(EquipmentMuscle, ...).where(EquipmentMuscle.muscle_group_id.in_(...)) 사용. 모델에서 EquipmentMuscle이 실제 존재(gym.py:185-198)하지만, 스펙에서 폐기되면 JOIN 불가능.
  - 수정: equipment_muscles 제거 후 근육 필터링을 exercise_muscles 경유로 변경. 머신 equipment_id 기반 exercise 역조회를 통해 exercise_muscles에서 근육 데이터 추출 (또는 근육 필터링 생략 가능).
- 🔴 **lines 973-1009 (free_stmt query with Exercise.default_equipment_id JOIN)** — 의존: `Exercise.default_equipment_id (컬럼)`
  - 깨짐: 라인 981: .join(Equipment, Equipment.id == Exercise.default_equipment_id). 모델에서 default_equipment_id 실제 존재(exercise.py:26-28)하지만, 스펙에서 제거되면 JOIN 실패.
  - 수정: 프리웨이트 기구 조회 변경: Exercise에서 load_mode 직접 조회 후, load_calc 상수로 기구 정보 제공 (Equipment JOIN 제거). Exercise.name_en과 load_mode로만 available_equipments 구성.
- 🔴 **line 984 (free_stmt WHERE Equipment.is_freeweight == True)** — 의존: `Equipment.is_freeweight (GENERATED column)`
  - 깨짐: 프리웨이트 필터링 WHERE 절에서 Equipment.is_freeweight == True 사용. 컬럼 제거 후 쿼리 실패.
  - 수정: Equipment JOIN 제거, Exercise.load_mode IN ('barbell', 'dumbbell', 'bodyweight', ...) 조건으로 직접 필터링.
- 🔴 **lines 1021-1056 (fb_free_stmt fallback query)** — 의존: `Exercise.default_equipment_id, Equipment.is_freeweight`
  - 깨짐: gym_id 없을 때 fallback 쿼리도 동일 패턴: 1029에서 .join(Equipment, Equipment.id == Exercise.default_equipment_id), 1032에서 Equipment.is_freeweight == True. 두 의존성 모두 제거 후 쿼리 완전 실패.
  - 수정: Exercise.load_mode 직접 필터링으로 Equipment JOIN 제거. Exercise.name_en과 load_mode로 available_equipments 구성.
- 🔴 **lines 1171-1179 (_resolve_label_to_ids machine_stmt)** — 의존: `Equipment.movement_label_en (컬럼)`
  - 깨짐: 라인 1173: WHERE sa_func.lower(Equipment.movement_label_en) == label_lc. 컬럼 제거 후 WHERE 절 실패.
  - 수정: exercise_equipment 정션(또는 exercise_muscles 역추적)과 Exercise.name_en 기반으로 변경. label과 일치하는 Exercise 먼저 찾고, 호환 기구 조회.
- 🔴 **lines 1195-1224 (_resolve_label_to_ids free_path with default_equipment_id)** — 의존: `Exercise.default_equipment_id (컬럼)`
  - 깨짐: 라인 1198-1207: Exercise.default_equipment_id를 조회해 Equipment 정보 반환. 컬럼 제거 후 프리웨이트 기구 정보 조회 불가능.
  - 수정: Exercise.load_mode 기반으로 변경. load_mode를 반환하고, load_calc에서 상수 바 무게 사용. equipment_id는 None 반환하되, 후속 처리에서 필요 시 machinery 케이스와 분기.
- 🔴 **lines 1250-1270 (_pick_equipment_for_exercise)** — 의존: `Exercise.default_equipment_id, Equipment.movement_label_en`
  - 깨짐: 라인 1251, 1257: default_equipment_id로 프리웨이트 기구 결정. 라인 1263: movement_label_en == name_en으로 머신 기구 검색. 두 컬럼 모두 제거 후 로직 완전 무너짐.
  - 수정: Exercise.load_mode로 분기. 프리웨이트(load_mode in {...})면 None 반환 (routine_exercises.equipment_id nullable로 변경됨). 머신은 exercise_equipment 정션으로 호환 기구 먼저 조회.
- 🔴 **lines 1315-1320 (_persist_day equipment_id NOT NULL assertion)** — 의존: `schema change: routine_exercises.equipment_id NOT NULL → nullable (Spec D7)`
  - 깨짐: 라인 1316-1320: eq_id is None이면 운동 제외 (equipment_id NOT NULL 검증). 하지만 모델(routine.py:92-94)에서는 현재 NOT NULL (= nullable 아님). 스펙이 nullable로 변경되면 코드와 모델 불일치 발생. 프리웨이트 운동(eq_id=None)이 저장되지 않는 버그.
  - 수정: equipment_id를 nullable로 선언하고, eq_id=None의 경우를 정상으로 처리 (라인 1316-1320 조건 제거 또는 변경).
- 🔴 **lines 939, 955, 959, 1173, 1263 (4개 함수에서 movement_label_en 사용)** — 의존: `Equipment.movement_label_en`
  - 깨짐: routines.py는 범위 밖이지만 4개 함수에서 movement_label_en 사용: _build_rag_profile SELECT/ORDER BY (line 939, 955, 959), _resolve_label_to_ids WHERE 필터 (line 1173), _pick_equipment_for_exercise WHERE 필터 (line 1263). 스펙 D6에서 칼럼 제거되면 모두 실패. 감사자가 gyms.py 항목만 보고, routines.py 반복 사용 누락.
  - 수정: movement_label_en SELECT/WHERE/ORDER BY 모두 제거. exercise.name_en 또는 equipment.name으로 통일. 스펙에서 머신도 movement_label_en == exercise.name_en 매핑이므로 name_en 정확 매칭 사용.
- 🔴 **lines 950-954 (EquipmentMuscle JOIN in _build_rag_profile)** — 의존: `EquipmentMuscle table`
  - 깨짐: 라인 951-954: EquipmentMuscle JOIN 명시적 사용. 스펙 D5에서 equipment_muscles 테이블 제거 예정. 테이블 미존재로 쿼리 실패. 감사자가 gyms.py 항목은 보고했으나, routines.py 동일 문제 누락.
  - 수정: EquipmentMuscle JOIN 제거. 머신은 이미 gym_equipments로 필터되므로 추가 근육 필터링 불가능 (phase 3에서 exercise_equipment 정션 추가 후 가능).
- 🔴 **lines 1029, 1032 (fallback freeweight query)** — 의존: `Exercise.default_equipment_id, Equipment.is_freeweight`
  - 깨짐: 라인 1029: Exercise.default_equipment_id로 Equipment JOIN. 라인 1032: Equipment.is_freeweight == True 필터. gym_id 미지정 fallback 경로에서도 동일 문제 반복. 감사자가 우선 경로 (line 981)만 보고, fallback 경로 누락.
  - 수정: 라인 1029의 Exercise.default_equipment_id JOIN 제거. Exercise.load_mode 기반 필터링으로 변경.
- 🔴 **_build_rag_profile function, lines 936-969 (machine_stmt query)** — 의존: `Query selects Equipment.movement_label_en (line 939) and filters Equipment.is_freeweight==False (line 947), uses equipment_muscles join (line 951)`
  - 깨짐: Spec D6 removes movement_label_en column. Spec D5 removes equipment_muscles table. Query will fail on column not found (line 939) and join on non-existent table (line 951). Spec also removes is_freeweight GENERATED column.
  - 수정: Replace machine_stmt query to use exercise_equipment N:M junction instead. Select Exercise.name_en, Equipment.id, Equipment.equipment_type from exercise_equipment JOIN exercises WHERE equipment_id IN gym_equipments. Remove movement_label_en select. Remove is_freeweight filter. Join exercise_muscles directly on Exercise instead of EquipmentMuscle.
- 🔴 **_build_rag_profile function, lines 971-1009 (free_stmt query)** — 의존: `Query filters Equipment.is_freeweight==True (line 984), joins Equipment on exercises.default_equipment_id (line 981)`
  - 깨짐: After redesign: (1) exercises.default_equipment_id column removed, (2) is_freeweight GENERATED column removed, (3) query logic breaks. Spec indicates freweight = exercises with load_mode in (barbell, ez_barbell, trap_bar, dumbbell, bodyweight, kettlebell, band).
  - 수정: Remove is_freeweight filter entirely. Replace Equipment.id join on default_equipment_id with SELECT from exercises WHERE load_mode IN ('barbell','ez_barbell','trap_bar','dumbbell','bodyweight','kettlebell','band'). Use exercise_muscles for primary muscle filtering. Equipment becomes optional.
- 🔴 **_build_rag_profile function, lines 1020-1056 (fb_free_stmt fallback query)** — 의존: `Same as free_stmt: filters is_freeweight==True (line 1032), joins on default_equipment_id (line 1029)`
  - 깨짐: Identical breaking points as free_stmt: default_equipment_id column removed, is_freeweight column removed. Fallback path must use load_mode filtering instead.
  - 수정: Same fix as free_stmt: replace is_freeweight filter with load_mode IN clause, remove default_equipment_id join, add load_mode column selection for equipment_type derivation.
- 🔴 **_resolve_label_to_ids function, lines 1152-1233** — 의존: `Line 1173: matches on Equipment.movement_label_en. Line 1198: reads Exercise.default_equipment_id. Line 1263: matches on Equipment.movement_label_en`
  - 깨짐: Spec D6 removes movement_label_en column. Spec removes default_equipment_id column. Function contract depends on equipment_label → movement_label_en → Equipment.id path for machines, and exercises.name_en → default_equipment_id path for freweight. Both paths broken after redesign.
  - 수정: Rewrite function contract per spec §5: (1) For machines: search exercise_equipment N:M with exercise.name_en==label to find equipment_id, then extract load_mode from exercise. (2) For freweight: search exercises.name_en==label, then use load_mode field directly instead of default_equipment_id join. Return (equipment_id, exercise_id, load_mode, pulley_ratio, bar_weight) tuple.
- 🔴 **_pick_equipment_for_exercise function, lines 1236-1270** — 의존: `Line 1251: reads Exercise.default_equipment_id. Line 1257: checks if default_equipment_id is not None. Line 1263: matches Equipment.movement_label_en == exercises.name_en`
  - 깨짐: After redesign, default_equipment_id column removed. Freweight exercises no longer have a single equipment_id. Movement_label_en column removed so machine matching by movement_label_en fails.
  - 수정: Restructure function: for freweight exercises (identified by load_mode), return None (equipment_id can be NULL per spec D7). For machine exercises, query exercise_equipment junction to find equipment_id from exercise_id. Update docstring to reflect new load_mode-based classification.
- 🔴 **_persist_day function, lines 1273-1320** — 의존: `Line 1309: calls _resolve_label_to_ids which returns (equipment_id, exercise_id, equipment_type, ...). Line 1316-1319: checks if eq_id is None and logs equipment_id NOT NULL constraint error`
  - 깨짐: After redesign (spec D7), routine_exercises.equipment_id becomes nullable for freweight exercises. Current code enforces NOT NULL at lines 1316-1319 and excludes exercises with eq_id==None. This logic was correct for old schema but breaks the new requirement that freweight exercises have NULL equipment_id.
  - 수정: Remove lines 1316-1319 constraint check. Allow equipment_id to be NULL for freweight exercises (identified by load_mode). Update RoutineExercise insertion to accept equipment_id=None. Update docstring to reflect that only machine exercises require equipment_id.
- 🔴 **_build_rag_profile function (lines 935-993, machine and free_weight paths)** — 의존: `Equipment.is_freeweight, Equipment.equipment_type enum values (barbell|dumbbell|bodyweight), Exercise.default_equipment_id, EquipmentMuscle table`
  - 깨짐: Lines 947 and 984 filter on is_freeweight COMPUTED column which will be deleted. Lines 975-981 perform INNER JOIN on default_equipment_id which will not exist. Line 951 joins EquipmentMuscle table which will be dropped.
  - 수정: Refactor dual-path logic to single exercise-centric query: join ExerciseMuscle -> Exercise, filter by Exercise.load_mode for classification, join exercise_equipment for machines. Remove is_freeweight and equipment_type filters.
- 🔴 **lines 936-956 (_build_rag_profile machine_stmt construction and execution)** — 의존: `Equipment.is_freeweight column, Equipment.movement_label_en column, EquipmentMuscle table/model (all to be removed)`
  - 깨짐: Line 947 filters by 'Equipment.is_freeweight == False' (column-not-found post-removal). Line 939 selects 'Equipment.movement_label_en' (column-not-found post-removal). Line 951 joins EquipmentMuscle (table-not-found post-removal). All three failures will cascade query execution failure.
  - 수정: Use Exercise.load_mode IN ('machine', 'cable') instead of is_freeweight filter. Use Exercise.name_en instead of Equipment.movement_label_en. Replace EquipmentMuscle JOIN with exercise_muscles JOIN through exercise_equipment table.
- 🔴 **Lines 839-902 (_build_rag_profile function)** — 의존: `Dual-path architecture using is_freeweight and equipment_muscles table`
  - 깨짐: Lines 947, 951-953 explicitly filter Equipment.is_freeweight == False for machines and use EquipmentMuscle JOINs. Lines 984, 988-990 filter is_freeweight == True for freeweight path. Both removal patterns are critical blocking points.
  - 수정: Replace dual-path with single exercise-centric query. Use exercise.load_mode to classify: baseline list (barbell|dumbbell|etc) = freeweight, otherwise machine. Update available_equipments construction.
- 🔴 **Lines 1152-1233 (_resolve_label_to_ids function)** — 의존: `movement_label_en for machine matching + default_equipment_id for freeweight`
  - 깨짐: Line 1173 matches against Equipment.movement_label_en (case-insensitive), line 1198 checks Exercise.default_equipment_id, line 1207 retrieves equipment from default_equipment_id. All three patterns depend on removed columns/fields.
  - 수정: Rewrite to use exercise.name_en for freeweight matching (no equipment label). For machines, match against exercise_equipment junction. Use load_mode to determine classification.
- 🔴 **Lines 1236-1270 (_pick_equipment_for_exercise function)** — 의존: `default_equipment_id + movement_label_en classification`
  - 깨짐: Line 1257 checks if ex_row.default_equipment_id is not None for freeweight classification. Line 1263 matches movement_label_en against exercise name_en for machine selection. Both will fail when columns are removed.
  - 수정: Update to use exercise.load_mode field instead of default_equipment_id check. For machines, use exercise_equipment junction instead of movement_label_en matching.
- 🔴 **lines 936-970 (_build_rag_profile machine path)** — 의존: `equipments.movement_label_en (line 939 select) + equipments.is_freeweight == False (line 947)`
  - 깨짐: Production code actively selects Equipment.movement_label_en and filters by is_freeweight==False. When schema removes these fields per WorkoutX spec, queries will fail with OperationalError. Currently working because fields exist but will break upon spec implementation.
  - 수정: Upon spec implementation: Rewrite to exercise-centric query using Exercise(load_mode) filter + exercise_equipment junction (machines only). Replace movement_label_en references with exercise.name_en.
- 🔴 **lines 971-1009 (_build_rag_profile free_weight path)** — 의존: `exercises.default_equipment_id (line 981 join) + Equipment.is_freeweight == True (line 984)`
  - 깨짐: free_stmt joins Equipment.id == Exercise.default_equipment_id and filters is_freeweight==True. Spec removes both. Query will fail with OperationalError when fields removed. Currently functional.
  - 수정: Upon spec implementation: Simplify to Exercise + ExerciseMuscle only. Equipment info determined via load_mode-based constants (load_calc.py). No junction needed.
- 🔴 **lines 1020-1070 (_build_rag_profile gym_id=None fallback)** — 의존: `equipments.is_freeweight == True (line 1032) + exercises.default_equipment_id (line 1029)`
  - 깨짐: fb_free_stmt uses Equipment.is_freeweight==True filter and default_equipment_id join. Both removed per spec. OperationalError upon implementation. Currently working fallback path.
  - 수정: Upon spec implementation: Simplify to Exercise + ExerciseMuscle. No equipment filtering needed for fallback.
- 🔴 **lines 1152-1191 (_resolve_label_to_ids machine path)** — 의존: `equipments.movement_label_en direct query (line 1172-1173)`
  - 깨짐: Direct query Equipment.movement_label_en == label. Field removed per spec = OperationalError. Core label resolution logic depends on this field. Currently functional.
  - 수정: Upon spec implementation: Rewrite to exercise-based resolution. Query Exercise.name_en → resolve to exercise_equipment junction for equipment. Label becomes exercise name.
- 🟠 **Lines 1172-1179 _resolve_label_to_ids function** — 의존: `Equipment.movement_label_en exact match for machine resolution`
  - 깨짐: Line 1173: WHERE lower(Equipment.movement_label_en)==label_lc will fail (column dropped). Machine label matching fails, equipment resolution fails, LLM-generated exercises excluded from routine.
  - 수정: Replace movement_label_en matching with Equipment.name or exercise.name_en matching.
- 🟠 **lines 457-463 (update_routine_exercise equipment_id NOT NULL logic)** — 의존: `schema change: routine_exercises.equipment_id NOT NULL → nullable (Spec D7)`
  - 깨짐: 라인 459-462: body.equipment_id is None이면 _pick_equipment_for_exercise로 강제 재선택, 실패 시 409 에러. 모델이 equipment_id를 nullable로 변경하면 프리웨이트 운동은 equipment_id 없이도 저장 가능해야 함. 현재는 반드시 기구를 선택하도록 강제.
  - 수정: Exercise.load_mode 확인 후 분기: 프리웨이트면 equipment_id=None 허용, 머신만 equipment_id 필수로 처리.
- 🟠 **lines 918-919 (주석의 dual-path 설명)** — 의존: `schema redesign: dual-path (is_freeweight) 제거, 단일 쿼리로 통합 (Spec §5)`
  - 깨짐: 라인 918-919 주석: '머신(is_freeweight=false) ... 프리웨이트(is_freeweight=true) dual-path'. 스펙에서 단일 가용성 규칙으로 통합되어 구현과 주석 불일치.
  - 수정: 주석과 로직을 Spec §5 단일 규칙으로 통합. 현재 dual-path 구조 설명 제거, Exercise.primary 근육 조건 또는 exercise_equipment 정션 조건으로 명시.
- 🟠 **lines 456-463 (_pick_equipment_for_exercise 호출 로직)** — 의존: `Exercise.load_mode field does not exist yet in ORM models`
  - 깨짐: 라인 460: picked = await _pick_equipment_for_exercise(new_ex_id, routine.gym_id, db). 이 함수 내에서 Exercise.load_mode를 참조하려면 모델에 load_mode 필드가 있어야 함. 현재 exercise.py에는 load_mode 필드 정의 없음(exercise.py:17-88 확인). 스펙에서 추가되면 모델 정의 필요.
  - 수정: Exercise 모델에 load_mode 필드 추가: load_mode: Mapped[str | None] = mapped_column(String(50), default=None) (또는 enum으로 정의). 마이그레이션 필요.
- 🟠 **lines 1236-1270 (_pick_equipment_for_exercise 함수 구현)** — 의존: `exercise_equipment junction table (new in Spec §5)`
  - 깨짐: 스펙에서 exercise_equipment 신규 N:M 정션(exercise_id, equipment_id, source, confidence) 추가됨. 현재 코드에는 이 정션을 사용하는 로직 전혀 없음. 머신 기구 선택 시 exercise_equipment → equipment_id 역조회가 필요한데, 모델과 쿼리 모두 미구현.
  - 수정: ExerciseEquipment 모델 정의 (또는 스펙 정션 이름으로 변경). _pick_equipment_for_exercise에서 exercise_equipment 정션 쿼리 추가: exercise_id 기반 equipment_id 조회.
- 🟠 **line 1441 (_fetch_user_1rms 호출)** — 의존: `exercise.load_mode-based weight calculation (derive_exercise_targets)`
  - 깨짐: 라인 1322-1335: derive_exercise_targets(..., equipment_type=eq_type, pulley_ratio=pulley_ratio, bar_weight=bar_weight). 현재 equipment_type 기반 계산. 스펙에서 exercise.load_mode 기반으로 변경되면 derive_exercise_targets 함수 시그니처/구현도 변경 필요 (load_mode 파라미터 추가, equipment_type 제거). 현재 코드에서는 equipment_type 파라미터 계속 사용하고 있음.
  - 수정: derive_exercise_targets 함수를 load_mode 기반으로 리팩토링: exercise.load_mode 전달, 함수 내에서 equipment_type 대신 load_mode로 분기. 또는 load_mode → equipment_type 변환 로직 추가.
- 🟠 **lines 1152-1233 (_resolve_label_to_ids docstring)** — 의존: `Return value contract change: equipment_id/exercise_id/equipment_type/pulley_ratio/bar_weight → load_mode 추가/변경`
  - 깨짐: 라인 1157-1165 docstring: '반환: (equipment_id, exercise_id, equipment_type, pulley_ratio, bar_weight)'. 스펙 변경 후 프리웨이트 경로는 load_mode 반환 필요. 현재 구현은 두 경로의 반환값 타입이 불일치할 수 있음 (None, exercise_id, None, 1.0, None vs equipment_id, exercise_id, equipment_type, ...). 호출처(라인 1309, 1322)에서 처리 시 타입 오류 가능.
  - 수정: 함수 반환값을 tuple 대신 TypedDict 또는 dataclass로 변경: {equipment_id, exercise_id, equipment_type, load_mode, pulley_ratio, bar_weight}. 호출처에서 언팩 로직 업데이트.
- 🟠 **lines 918-919 (_build_rag_profile docstring)** — 의존: `Architecture documentation`
  - 깨짐: 라인 918-919 주석: '머신(is_freeweight=false) × equipment_muscles, 프리웨이트(is_freeweight=true) × exercises'. 실제 스펙 D5, D6에서 두 항목 모두 제거되므로 dual-path 아키텍처 불가능. exercise-centric 단일 경로로 통합되어야 함. 코드-문서 불일치.
  - 수정: 라인 918-919 주석 업데이트. 새 아키텍처: '모든 운동 (머신/프리) → exercise_muscles 경로 사용. 머신만 exercise_equipment 추가 정션 사용.'
- 🟠 **_build_rag_profile function, lines 962-969 and 1002-1009** — 의존: `Code constructs available_equipments with 'source': 'MACHINE' and 'source': 'FREE' tags that are used in rag.py _build_routine_prompt at lines 414-415`
  - 깨짐: Spec §5 indicates redesign removes [MACHINE]/[FREE] distinction from prompt output. However, routines.py still tags equipments with source field (lines 967, 1007) and rag.py still uses these tags (line 414). Spec says tags should be removed but code still produces them - mixed state creates ambiguity about contract.
  - 수정: Decide whether to: (1) remove source field from available_equipments structure entirely and update prompt template to not use tags, OR (2) keep source for internal routing but remove tags from prompt output only. Current state where code produces unused source tags is technical debt.
- 🟠 **UpdateRoutineExerciseRequest class (lines 143-154)** — 의존: `Exercise.load_mode field (to be added) + RoutineExercise.equipment_id nullability`
  - 깨짐: PATCH endpoint at line 147 allows equipment_id update without validation. Post-redesign, freeweight exercises must have NULL equipment_id. Schema lacks load_mode field to enable client-side validation. Endpoint should reject non-NULL equipment_id for freeweight exercises.
  - 수정: Add load_mode field to UpdateRoutineExerciseRequest schema or validate at endpoint layer. Implement validator: if exercise.load_mode in freeweight set, reject non-NULL equipment_id in PATCH.
- 🟠 **lines 971-1009 (_build_rag_profile free_stmt construction and execution)** — 의존: `Exercise.default_equipment_id column (to be removed), Equipment.is_freeweight column (to be removed)`
  - 깨짐: Line 981 JOINs 'Equipment, Equipment.id == Exercise.default_equipment_id' (column-not-found after removal). Line 984 filters 'Equipment.is_freeweight == True' (column-not-found after removal). Query execution will fail on both column references.
  - 수정: Use Exercise.load_mode IN ('barbell', 'dumbbell', 'bodyweight', 'kettlebell', 'band', 'ez_barbell', 'trap_bar') instead. Skip Equipment JOIN entirely for freeweight exercises.
- 🟠 **Lines 866-905 (target muscle region resolution in _build_rag_profile)** — 의존: `MuscleGroup.body_region value mapping accuracy`
  - 깨짐: Lines 867-878 normalize user input to body_region values. Line 899 filters MuscleGroup.body_region.in_(body_regions). If _REGION_ALIASES maps to incorrect body_region values, query returns 0 rows. Need to verify actual database MuscleGroup.body_region enum values match normalize logic.
  - 수정: Validate that _REGION_ALIASES (lines 867-878) maps only to actual WorkoutX bodyPart values present in database. Verify MuscleGroup seed data uses correct body_region values.
- 🟠 **Lines 867-878 (_REGION_ALIASES normalization mapping)** — 의존: `MuscleGroup.body_region enum validation`
  - 깨짐: Lines 867-878 normalize user input (shoulder→shoulders, abs→core, etc) and line 899 filters MuscleGroup.body_region.in_(body_regions). If actual database MuscleGroup.body_region values differ from normalized strings (e.g., if database uses 'shoulder' but code produces 'shoulders'), query returns 0 rows with no error. Need explicit validation that aliases match real database enum values.
  - 수정: Add runtime validation: after normalizing body_regions, verify they exist in database with SELECT DISTINCT MuscleGroup.body_region. Log warning if user selects unmapped region. Or hardcode aliases to verified working values with schema comments.
- 🟠 **lines 1188-1191 (_resolve_label_to_ids machine→exercise name matching contract)** — 의존: `Equipment.movement_label_en == label assumption → Exercise.name_en == label assumption`
  - 깨짐: Code assumes Equipment.movement_label_en == label implies Exercise.name_en == label (line 1190-1191). Spec removes movement_label_en + adds exercise_equipment junction. Direct name-to-name matching becomes exercise-to-equipment-to-exercise indirect path. Matching contract fundamentally changes.
  - 수정: Upon spec implementation: Remove Equipment.movement_label_en premise. Match Exercise.name_en directly. If exercise found, lookup equipment via exercise_equipment junction (if machine) or load_mode constant (if freeweight). Simplify contract.
- 🟡 **lines 468-476 (update_routine_exercise gym_id기반 기구 검증)** — 의존: `schema change: routine_exercises.equipment_id nullable, 프리웨이트=NULL 정책`
  - 깨짐: 라인 468-476: eq_id not None이면 gym_equipments 검증 실행. 프리웨이트(eq_id=None)는 gym 제약 없으므로 이 검증을 무시해야 함. 현재는 eq_id not None인 경우만 실행되어 논리상 정상이지만, nullable 변경 후 명시성 부족.
  - 수정: 주석 추가: '프리웨이트(eq_id=None)는 gym 제약 없음'. 필요 시 조건 명확화.
- 🟡 **_build_rag_profile comment, lines 971-972** — 의존: `Documentation comment describing data flow for freweight query`
  - 깨짐: Comment is outdated: states 'exercise_muscles × exercises × equipments(default_equipment_id, is_freeweight=true)' but both default_equipment_id and is_freeweight are removed. While comments don't cause runtime breaks, misleading documentation causes future maintenance bugs when developers try to understand data flow.
  - 수정: Update comment to reflect new data flow: 'exercises with load_mode IN baseline list, use exercise_muscles for muscle filtering'

### `gyms.py` (15)
- 🔴 **Lines 20-31 imports, line 581 EquipmentMuscle JOIN** — 의존: `EquipmentMuscle model import and JOIN queries (deprecated table)`
  - 깨짐: gyms.py imports EquipmentMuscle at line 22. Line 581 performs JOIN to fetch machine muscle data. Table DROP will cause JOIN to fail. Entire _fetch_machine_equipments_by_muscle function fails.
  - 수정: Remove EquipmentMuscle import. Rewrite lines 550-610 to use exercise_equipment -> exercise_muscles path for machine muscle queries.
- 🔴 **Lines 550-610 _fetch_machine_equipments_by_muscle function** — 의존: `EquipmentMuscle JOIN for machine muscle filtering (deprecated table)`
  - 깨짐: Entire function uses EquipmentMuscle.join() at line 581 to fetch machine equipment by target muscle. Table will be dropped. Function called by GET /gyms/{gymId}/muscles/{muscleGroupId}/equipment endpoint (line 657). Muscle-filtered equipment browsing endpoint completely non-functional post-migration.
  - 수정: Rewrite function to use gym_equipments -> exercise_equipment (machines only) -> exercise_muscles -> muscle filter path.
- 🔴 **list_equipments_by_muscle() lines 576, 581, 587-588** — 의존: `EquipmentMuscle, Equipment.movement_label_ko, Equipment.is_freeweight`
  - 깨짐: 라인 576: Equipment.movement_label_ko 선택 (제거 예정). 라인 581-588: EquipmentMuscle JOIN 및 필터링 (테이블 제거 예정). equipment_type.notin_() 우회책 사용하지만 is_freeweight 칼럼 제거되면 로직 완전히 무효화.
  - 수정: Equipment → exercise_equipment → Exercise → exercise_muscles 경로로 쿼리 변경. movement_label_ko 제거, equipment.name 사용. is_freeweight 명시적 필터 제거, equipment.equipment_type이 freeweight 타입인지 확인으로 대체.
- 🔴 **list_equipments_by_muscle() line 626** — 의존: `Exercise.default_equipment_id`
  - 깨짐: 라인 626: Exercise.default_equipment_id로 Equipment JOIN 실행. 스펙 D2, D6에서 제거되므로 JOIN 대상 없음. freeweight 행 반환 0개.
  - 수정: Exercise.load_mode IN (barbell, ez_barbell, trap_bar, dumbbell, bodyweight, kettlebell, band) 필터로 변경. Equipment JOIN 제거. load_mode별 대표 기구 반환 또는 exercise_id+load_mode 직접 반환.
- 🔴 **MachineItem class (line 137-145), specifically line 602 in gyms.py API** — 의존: `Equipment.movement_label_ko (to be removed)`
  - 깨짐: Line 602 in list_equipments_by_muscle reads: row.movement_label_ko or row.name. Once movement_label_ko column is deleted, query at line 576 SELECT Equipment.movement_label_ko will fail (column not found error).
  - 수정: Replace line 602 with logic deriving from exercise_equipment N:M junction. Alternative: compute from exercise.load_mode classification instead of stored column.
- 🔴 **list_equipments_by_muscle endpoint, lines 616-626 (free_weights path)** — 의존: `Exercise.default_equipment_id FK (to be removed)`
  - 깨짐: Line 626 performs: .join(Equipment, Equipment.id == Exercise.default_equipment_id). If default_equipment_id column is deleted, INNER JOIN will fail with column not found or FK violation. Query will not execute.
  - 수정: Replace INNER JOIN on default_equipment_id with filter on Exercise.load_mode IN (barbell|dumbbell|bodyweight|kettlebell|ez_barbell|trap_bar|band). Use exercise_equipment junction for machine exercises only.
- 🔴 **Lines 563-643 (_fetch_available_equipment dual-path)** — 의존: `is_freeweight filter + equipment_muscles JOINs + default_equipment_id path`
  - 깨짐: Lines 570-592 implement machine path with EquipmentMuscle JOINs and equipment_type filter. Lines 610-645 implement freeweight path using Exercise.default_equipment_id INNER JOIN. Both paths depend on removed patterns.
  - 수정: Replace dual-path with unified query using exercise_equipment junction for machines + load_mode check for freeweight. Remove EquipmentMuscle JOINs and is_freeweight filter.
- 🟠 **Lines 576, 602 _machine_row function** — 의존: `Equipment.movement_label_ko column (spec D6 removal)`
  - 깨짐: Line 576 references Equipment.movement_label_ko in column selection. Line 602 uses it as fallback for label construction. Column DROP causes AttributeError.
  - 수정: Use Equipment.name (Korean) or exercise.name (Korean) via exercise_equipment junction instead.
- 🟠 **list_equipments_by_muscle() line 602** — 의존: `Equipment.movement_label_ko`
  - 깨짐: 라인 602: row.movement_label_ko or row.name 체인. movement_label_ko 칼럼 제거되면 AttributeError 발생.
  - 수정: movement_label_ko 체인 제거, equipment.name 직접 사용: label=row.name
- 🟠 **list_equipments_by_muscle endpoint, lines 545-662** — 의존: `Line 547: comment references equipment_muscles table. Line 570: comment references is_freeweight=false filter. Lines 581, 626: joins on EquipmentMuscle and Equipment.default_equipment_id`
  - 깨짐: Spec removes equipment_muscles table (D5) and is_freeweight GENERATED column (D6) and default_equipment_id column (D2). Code uses all three. Query will fail on non-existent table/columns.
  - 수정: Update gym machines query (lines 572-593) to join exercise_equipment instead of equipment_muscles. Filter on exercises with load_mode NOT IN baseline list. For freweights (lines 616-635), remove default_equipment_id join and is_freeweight filter. Query exercises with load_mode IN baseline list instead.
- 🟠 **ExerciseItem class (line 120-127)** — 의존: `Exercise.load_mode field (to be added but not yet in ORM/schema)`
  - 깨짐: Schema does not include load_mode field. Frontend cannot determine equipment classification (barbell vs cable vs cardio) without this field. Post-redesign, APIs that return ExerciseItem must include load_mode for client-side validation and UI logic that depends on exercise type.
  - 수정: Add load_mode: str field to ExerciseItem schema. Populate from Exercise.load_mode in all exercise response endpoints. Update mobile TypeScript types accordingly.
- 🟠 **Gym API endpoints filtering equipment by muscle_id** — 의존: `EquipmentMuscle model used in muscle-based equipment filtering`
  - 깨짐: Code confirmed via grep uses '.join(EquipmentMuscle, EquipmentMuscle.equipment_id == Equipment.id)' with involvement filter to find gym equipment by target muscle. After equipment_muscles table removal, query will fail with table-not-found error. This blocks muscle-based equipment search for gym facilities.
  - 수정: Replace with exercise_equipment→exercise_muscles joins. Filter to machine exercises only via Exercise.load_mode.
- 🟠 **Lines 576, 602** — 의존: `equipment.movement_label_ko column removal`
  - 깨짐: Line 576 selects movement_label_ko in query, line 602 uses it as fallback label (row.movement_label_ko or row.name). Column will be removed per spec D6.
  - 수정: Use equipment.name or equipment.name_en instead of movement_label_ko. Update label fallback chain to: name_en → name.
- 🟡 **list_equipments_by_muscle docstring, lines 545-549** — 의존: `Function docstring describes implementation using equipment_muscles and is_freeweight`
  - 깨짐: Both equipment_muscles table and is_freeweight column are removed per spec. Docstring becomes misleading for future maintainers - while it doesn't cause runtime error immediately, it will cause confusion when code is refactored.
  - 수정: Update docstring to document new data flow: machines come from exercise_equipment N:M junction, freweights from exercises with load_mode in baseline list.
- 🟡 **Lines 599-607 (MachineItem response construction)** — 의존: `movement_label_ko fallback removal`
  - 깨짐: Line 602 constructs label fallback: row.movement_label_ko or row.name. When movement_label_ko column is removed, this expression silently fails to None (since movement_label_ko field won't exist on ORM row object). MachineItem.label becomes None instead of falling back to equipment.name.
  - 수정: Update label construction to: row.name_en or row.name (verified columns that remain). Or add migration to backfill name_en before removing movement_label_ko.

### `gym.py` (14)
- 🔴 **Equipment class, lines 134-135** — 의존: `equipment.movement_label_en and movement_label_ko columns (spec D6 removal)`
  - 깨짐: Columns will be dropped. routines.py (lines 939, 955, 1173) and gyms.py (lines 576, 602) directly reference these in actual WHERE and ORDER BY clauses. AttributeError on column access post-migration.
  - 수정: Remove movement_label_* column mappings. Use Equipment.name or exercise.name_en via exercise_equipment junction.
- 🔴 **Equipment class, lines 136-139** — 의존: `equipment.is_freeweight GENERATED STORED column (spec D6 removal)`
  - 깨짐: GENERATED column will be dropped. routines.py (lines 947, 984, 1032), admin.py (line 394), and gyms.py (line 570) use WHERE Equipment.is_freeweight==True/False for filtering. AttributeError on WHERE clause post-migration.
  - 수정: Remove Equipment.is_freeweight mapping. Replace filtering with Exercise.load_mode or Equipment.equipment_type branching.
- 🔴 **EquipmentMuscle class definition, lines 185-198** — 의존: `equipment_muscles table and model (spec D5 deprecation)`
  - 깨짐: Table will be dropped. gyms.py (lines 581-588) joins EquipmentMuscle to fetch machine muscle data. JOIN will fail post-migration. Model is imported in __init__.py and gyms.py.
  - 수정: Delete EquipmentMuscle model and imports. Fetch machine muscles via gym_equipments -> exercise_equipment -> exercise_muscles path.
- 🔴 **Equipment class lines 134-139** — 의존: `Equipment.movement_label_ko, Equipment.movement_label_en, Equipment.is_freeweight (computed column)`
  - 깨짐: 라인 134-135: movement_label_ko/en 칼럼 정의. 라인 136-139: is_freeweight Computed 칼럼 정의. 스펙 D6에서 제거 예정. DB migration 후 SELECT/WHERE 쿼리에서 칼럼 미존재.
  - 수정: migration에서 movement_label_ko, movement_label_en, is_freeweight 칼럼 DROP. freeweight 분류는 Exercise.load_mode로만 처리.
- 🔴 **EquipmentMuscle model lines 185-199** — 의존: `EquipmentMuscle table and model`
  - 깨짐: EquipmentMuscle 모델과 equipment_muscles 테이블 정의. 스펙 D5에서 테이블 제거 예정. migration 후 쿼리/관계 모두 실패.
  - 수정: EquipmentMuscle 모델 및 테이블 DROP. 근육 정보는 exercise_equipment → exercise → exercise_muscles 경로로만 제공.
- 🔴 **Equipment model, lines 134-139** — 의존: `movement_label_en column at line 135, is_freeweight GENERATED column at lines 136-139`
  - 깨짐: Both columns are defined in ORM model but do not exist in target schema after removal. Any read/write to these mapped fields will fail at runtime.
  - 수정: Remove lines 135 and 136-139 from Equipment model definition. Update all query paths that reference equipment.is_freeweight or equipment.movement_label_en to use exercise.load_mode instead.
- 🔴 **EquipmentMuscle model, lines 185-198** — 의존: `Entire EquipmentMuscle class defining equipment_muscles table`
  - 깨짐: equipment_muscles table is removed entirely. All muscle mapping comes from exercise_muscles via exercise_equipment junction. EquipmentMuscle ORM class becomes orphaned.
  - 수정: Delete EquipmentMuscle class entirely (lines 185-198). Remove any code querying EquipmentMuscle. Update muscle filtering queries to go through exercise_equipment → exercise_muscles instead.
- 🔴 **EquipmentMuscle class (lines 185-198)** — 의존: `equipment_muscles table (to be removed entirely)`
  - 깨짐: ORM model maps to table being dropped. Code at gyms.py line 581 and routines.py line 951 actively queries this model via .join(EquipmentMuscle, ...). Post-migration, these joins will fail with 'relation equipment_muscles does not exist'.
  - 수정: Delete EquipmentMuscle model. Update gyms.py line 581 and routines.py line 951-953 to derive machine exercise targeting from exercise_equipment N:M junction + exercise_muscles instead.
- 🔴 **Equipment class, lines 134-139 (three mapped_column declarations)** — 의존: `equipments.movement_label_ko, equipments.movement_label_en, equipments.is_freeweight columns (all to be removed)`
  - 깨짐: ORM maps three columns: 'movement_label_ko: Mapped[str | None]' (line 134), 'movement_label_en: Mapped[str | None]' (line 135), 'is_freeweight: Mapped[bool | None] = mapped_column(Boolean, Computed(...))' (lines 136-139). After column removal, accessing equipment.is_freeweight, equipment.movement_label_en, or equipment.movement_label_ko will raise AttributeError.
  - 수정: Remove all three mapped_column declarations. For freeweight classification, use 'Exercise.load_mode IN (...)' filter dynamically instead of storing on Equipment.
- 🔴 **EquipmentMuscle class, lines 185-199 (entire class definition)** — 의존: `equipment_muscles table + EquipmentMuscle model (both to be removed)`
  - 깨짐: ORM class declaration maps to equipment_muscles table at line 186 '__tablename__ = "equipment_muscles"'. After table removal, ORM schema initialization fails with table-not-found. All queries using EquipmentMuscle (e.g., .join(EquipmentMuscle, ...) in routines.py) will fail.
  - 수정: Remove entire EquipmentMuscle class from gym.py. Derive machine muscle relationships via Exercise.exercise_muscles through the exercise_equipment N:M junction table instead.
- 🔴 **Lines 134-139** — 의존: `equipments.movement_label_ko/en columns + is_freeweight GENERATED column removal`
  - 깨짐: movement_label_ko (line 134), movement_label_en (line 135), and is_freeweight computed column (lines 136-139) are defined in the model and actively used in routines.py (lines 939, 959, 1173, 1263) and gyms.py (lines 576, 602). All will be removed per spec.
  - 수정: Remove movement_label_ko, movement_label_en columns and is_freeweight computed column. Move load_mode to Exercise model instead. Update all callers to use load_mode classification.
- 🔴 **Lines 185-198** — 의존: `EquipmentMuscle model + equipment_muscles table removal`
  - 깨짐: Entire EquipmentMuscle class is present (lines 185-198) and actively used in routines.py (_build_rag_profile lines 951-953) and gyms.py (lines 581, 588) with JOINs and WHERE filters on this table.
  - 수정: Delete entire EquipmentMuscle class. Rewrite all queries to derive muscle targets from exercise_muscles via exercise_equipment junction instead.
- 🟠 **Equipment class (lines 134-139)** — 의존: `Equipment.movement_label_en, movement_label_ko, is_freeweight columns (to be removed)`
  - 깨짐: ORM defines these fields; routines.py line 939 reads movement_label_en. If column is deleted without removing ORM field, SQLAlchemy will fail on lazy load or refresh with 'column does not exist' error.
  - 수정: Remove movement_label_ko, movement_label_en, and is_freeweight fields from Equipment ORM model. Update routines.py line 939 to derive label from exercise name or load_mode enum.
- 🟠 **EquipmentBodyCategory enum (lines 18-24)** — 의존: `Equipment.category enum values mapped to WorkoutX bodyPart taxonomy`
  - 깨짐: Current enum: {chest, back, shoulders, arms, core, legs}. Redesign changes to WorkoutX: {chest, back, shoulders, upper arms, lower arms, waist, legs, glutes, etc}. Enum values 'arms' and 'core' do not exist in WorkoutX. Data migration must map old->new but enum definition must be updated or category becomes string field.
  - 수정: Update EquipmentBodyCategory enum to match WorkoutX taxonomy or convert to non-enum string field. Run data migration to map: arms->{upper arms|lower arms}, core->{waist|upper abs|lower abs}. Update all schema definitions accordingly.

### `exercise.py` (12)
- 🔴 **Exercise class, lines 26-28** — 의존: `exercises.default_equipment_id (FK, nullable)`
  - 깨짐: Column exists in ORM mapping but will be dropped by migration. Runtime attribute access will raise AttributeError. routines.py (lines 981, 1198, 1207, 1257) and gyms.py (line 617) directly access this field.
  - 수정: Remove Exercise.default_equipment_id mapping or replace with load_mode-based branching
- 🔴 **Exercise class, lines 31-33** — 의존: `Exercise.equipment_maps relationship referencing ExerciseEquipmentMap`
  - 깨짐: exercise_equipment_map table will be dropped. Relationship load will fail with FK constraint violation. seed.py (lines 530-537) still performs writes to this table.
  - 수정: Remove Exercise.equipment_maps relationship. Replace with exercise_equipment N:M junction or load_mode branching.
- 🔴 **ExerciseEquipmentMap class definition, lines 37-48** — 의존: `exercise_equipment_map table and ORM model (to be deprecated)`
  - 깨짐: Model is deprecated per spec. Table will be dropped. __init__.py exports this model; seed.py and admin.py still use it. Cannot instantiate after migration.
  - 수정: Delete ExerciseEquipmentMap entirely. Redefine as ExerciseEquipment with (exercise_id, equipment_id, source, confidence) for machines only.
- 🔴 **Exercise class fields** — 의존: `Exercise.load_mode field (spec D2 new field, currently missing from ORM)`
  - 깨짐: Spec D2 adds exercises.load_mode (varchar: barbell|ez_barbell|trap_bar|dumbbell|bodyweight|kettlebell|band|cable|machine|cardio) for exercise classification. No mapping exists in current Exercise ORM. All load_mode-based filtering in routines.py, load_calc.py, rag.py will fail with AttributeError. Exercise classification impossible post-spec change.
  - 수정: Add Exercise.load_mode field: load_mode: Mapped[str | None] = mapped_column(String(50), default=None). Create migration to populate from exercise_equipment, equipment_type, and category.
- 🔴 **Exercise class lines 26-28, 31-33** — 의존: `Exercise.default_equipment_id (column), ExerciseEquipmentMap model and relationship`
  - 깨짐: 라인 26-28: default_equipment_id FK 칼럼 정의. 라인 31-33: equipment_maps 관계 정의 (ExerciseEquipmentMap). 스펙 D2, D3, D5, D6에서 두 항목 모두 제거 예정. DB migration 후 ORM 쪽근 실패.
  - 수정: migration에서 default_equipment_id 칼럼 DROP, equipment_maps 관계 제거. load_mode VARCHAR enum 칼럼 추가. exercise_equipment 관계 추가 (새 N:M 정션).
- 🔴 **Exercise model, lines 26-28 (default_equipment_id), lines 31-32 (equipment_maps relationship)** — 의존: `default_equipment_id FK column mapped at lines 26-28 and ExerciseEquipmentMap relationship at lines 31-32`
  - 깨짐: default_equipment_id column and exercise_equipment_map (eem) table are removed per spec. ORM model still defines these fields. After migration, queries accessing these fields will fail.
  - 수정: Remove lines 26-28 (default_equipment_id field and FK). Remove lines 31-32 (equipment_maps relationship). Add load_mode field (varchar enum: barbell|ez_barbell|trap_bar|dumbbell|bodyweight|kettlebell|band|cable|machine|cardio).
- 🔴 **ExerciseEquipmentMap model definition, lines 37-48** — 의존: `Entire ExerciseEquipmentMap class and Exercise.equipment_maps relationship back_populates reference`
  - 깨짐: exercise_equipment_map table is removed by redesign. New exercise_equipment junction has different schema (exercise_id, equipment_id, source, confidence). ExerciseEquipmentMap ORM class becomes orphaned with no table to map to.
  - 수정: Delete ExerciseEquipmentMap class entirely (lines 37-48). Create new ExerciseEquipment model with columns: exercise_id (FK, PK), equipment_id (FK, PK), source (varchar: seed|gemini), confidence (numeric nullable). Update Exercise relationship to new ExerciseEquipment class.
- 🔴 **Exercise class (lines 26-28)** — 의존: `Exercise.default_equipment_id FK column (to be removed)`
  - 깨짐: Field is defined with FK constraint to equipments.id. If migration deletes column without removing ORM field definition, ORM layer will fail on session.refresh() or relationship traversal. Model must be updated to match schema.
  - 수정: Delete column in migration. Remove Exercise.default_equipment_id field from ORM model in exercise.py.
- 🔴 **ExerciseEquipmentMap class (lines 37-48)** — 의존: `exercise_equipment_map table (to be replaced by exercise_equipment N:M)`
  - 깨짐: ORM model maps to table that will be dropped. Any code instantiating this model post-migration or querying via session.query(ExerciseEquipmentMap) will raise 'table does not exist' error.
  - 수정: Delete ExerciseEquipmentMap model entirely. Create new ExerciseEquipment model mapping exercise_equipment table (exercise_id, equipment_id, source, confidence).
- 🔴 **Exercise class, lines 31-33 (equipment_maps relationship declaration)** — 의존: `ExerciseEquipmentMap model + exercise_equipment_map table (both to be removed)`
  - 깨짐: ORM declares 'equipment_maps: Mapped[list["ExerciseEquipmentMap"]] = relationship(back_populates="exercise", cascade="all, delete-orphan")'. After model/table removal, relationship access raises model-not-found. Cascade delete on Exercise deletion will fail.
  - 수정: Remove equipment_maps relationship entirely. After creating new ExerciseEquipment model, add relationship to it for machines only.
- 🔴 **Lines 26-28, 31-33** — 의존: `exercises.default_equipment_id column + ExerciseEquipmentMap model removal`
  - 깨짐: default_equipment_id FK (line 26-28) and equipment_maps relationship (line 31-33) directly reference the ExerciseEquipmentMap table which will be removed in PR-5. Both are active in runtime code.
  - 수정: Remove default_equipment_id field (lines 26-28) and equipment_maps relationship (lines 31-33). Add load_mode varchar field for exercise classification instead.
- 🟠 **Exercise class, lines 26-28 (default_equipment_id field declaration)** — 의존: `Exercise.default_equipment_id column (to be removed in PR-5)`
  - 깨짐: ORM declares 'default_equipment_id: Mapped[uuid.UUID | None] = mapped_column(...)' at lines 26-28. After column removal, accessing ex.default_equipment_id will raise AttributeError. ORM schema validation will fail on model initialization.
  - 수정: After PR-5 migration removes column, replace default_equipment_id with Exercise.load_mode field (Mapped[str] with enum values). Remove FK relationship to equipments entirely.

### `test_routine_equipment_rag.py` (8)
- 🔴 **lines 511-537 (test_free_weight_path_returns_both_ids)** — 의존: `Exercise.default_equipment_id field access (lines 516-519)`
  - 깨짐: Test mocks ex_row.default_equipment_id and verifies equipment lookup via this field. Spec removes default_equipment_id. Test currently passes via mock, but production code redesign will invalidate assumption. Free weight resolution contract changes fundamentally.
  - 수정: Upon spec implementation: Redesign to load_mode-based classification. Freeweights: equipment_id=NULL (or omitted). Machines: equipment_equipment junction. Remove default_equipment_id from test expectations.
- 🔴 **lines 318-366 (test_free_weight_label_resolved_and_saved)** — 의존: `fake_resolve returns equipment_id for freeweight (line 328, eq_id persisted)`
  - 깨짐: Test expects freeweight resolution to return equipment_id (line 360: assert rex.equipment_id == eq_id). Spec nullable-ifies equipment_id for freeweights. Test assumption breaks upon implementation.
  - 수정: Upon spec implementation: Change test to expect equipment_id=NULL for freeweights. Verify load_mode classification instead. Equipment identification via load_mode, not equipment_id.
- 🟠 **lines 487-509 (test_machine_path_returns_equipment_and_exercise)** — 의존: `movement_label_en matching verification (line 503 _resolve_label_to_ids call)`
  - 깨짐: Test calls _resolve_label_to_ids('Cable Fly') to verify movement_label_en matching path. Test passes via mock, but spec removes movement_label_en. When production code implements spec, this test's assumption (machinery search by label) becomes invalid.
  - 수정: Upon spec implementation: Rewrite to verify exercise-based resolution. 'Cable Fly' label → Exercise.name_en match → exercise_equipment junction lookup. Test machinery search contract changes.
- 🟠 **lines 116-156 (TestBuildRagProfileEquipments.test_machine_and_free_both_in_available_equipments DB query sequence)** — 의존: `Dual-path (machine_stmt/free_stmt) query assumption + query order comments`
  - 깨짐: Comments document dual-path structure (lines 130-134). Spec consolidates to single exercise-centric path. Query sequence, mock setup order, available_equipments construction all assume separate machine/free queries. Entire test structure assumes removed architecture.
  - 수정: Upon spec implementation: Consolidate test to single exercise query path. Remove dual-path mock setup. Exercise → ExerciseMuscle → exercise_equipment (machines) junction structure. Update mock order + assertion logic.
- 🟠 **lines 199-240 (TestBuildRagNoEquipments gym_id presence/absence filtering strategy)** — 의존: `gym_id check → (machine+free) vs (fb_free fallback) branching logic`
  - 깨짐: Test validates gym_id-dependent query branching (gym_id → both, no gym_id → fallback). Spec removes branching; both machine and free queries become exercise-centric with optional gym filter. Test's conditional structure + mock setup + assertions based on removed branching. Filtering strategy changes.
  - 수정: Upon spec implementation: Rewrite test to single exercise query path. gym_id affects exercise_equipment junction filter only (machines), not freeweights. Consolidate test structure. Update available_equipments assertions.
- 🟡 **lines 94-110 (_machine_row, _free_row helpers)** — 의존: `movement_label_en mock (line 97) + equipment_type (line 100)`
  - 깨짐: Helper mocks movement_label_en field that spec removes. Mock-based test currently passes, but helper design assumes removed field. When spec implemented and production code changes, test's mock structure becomes obsolete.
  - 수정: Upon spec implementation: Redesign helpers to use exercise.load_mode instead of movement_label_en. Remove equipment_type mock from _machine_row (will come from exercise_equipment junction).
- 🟡 **lines 540-552 (test_both_paths_fail_returns_none_ids dual-path failure testing)** — 의존: `machine_stmt.first()→None AND Exercise.name_en→None two-path failure contract`
  - 깨짐: Test verifies both machine_stmt and Exercise query fail → (None, None) return. Spec removes dual-path. Single exercise path means only one failure point (Exercise not found). Test's failure scenario contract invalid.
  - 수정: Upon spec implementation: Simplify test to single failure path. Exercise.name_en not found → (None, None, None, ...) return. Remove machine_stmt mock. Consolidate to single exercise resolution contract.
- 🟡 **lines 395-425 (test_unresolved_equipment_excluded_from_results equipment_id NOT NULL filtering)** — 의존: `equipment_id NOT NULL check for result inclusion (lines 397-401)`
  - 깨짐: Test verifies equipment_id=None results are excluded (equipment_id NOT NULL filtering). Spec nullable-ifies equipment_id for freeweights, making NULL a valid state. Filtering logic that excludes NULL becomes incorrect. Test's exclusion assumption invalid upon implementation.
  - 수정: Upon spec implementation: Modify test expectations. Freeweight exercises with equipment_id=NULL are now valid (should not exclude). Only exclude if exercise resolution failed entirely. Restructure test for load_mode-based classification where NULL is normal for freeweights.

### `admin.py` (5)
- 🔴 **seed_exercises_from_workoutx() lines 394, 429-430** — 의존: `Equipment.is_freeweight, Exercise.default_equipment_id`
  - 깨짐: Line 394 직접 확인: Equipment.is_freeweight == True 필터링 실행. 라인 429-430: values['default_equipment_id']와 set_['default_equipment_id'] 설정. 스펙 D6에서 두 칼럼 모두 제거 예정이므로 진짜 깨짐.
  - 수정: is_freeweight 필터 제거하고, wx_equipment을 load_mode enum(barbell|ez_barbell|trap_bar|dumbbell|bodyweight|kettlebell|band|cable|machine|cardio)로 변환하여 exercises.load_mode에 직접 설정. 프리웨이트(barbell/ez_barbell/trap_bar/dumbbell/bodyweight/kettlebell/band)는 load_mode만 설정, exercise_equipment 행 생성 안함. 머신/케이블은 load_mode 설정 후 phase 3에서 exercise_equipment 행 추가.
- 🔴 **Lines 372-484 (seed_exercises_from_workoutx function)** — 의존: `is_freeweight filter and default_equipment_id assignment`
  - 깨짐: Lines 394 use Equipment.is_freeweight filter explicitly (noqa: E712), lines 429-430 set default_equipment_id on exercises. Both patterns will break when is_freeweight GENERATED column is removed.
  - 수정: Replace is_freeweight filter with load_mode field check. Populate exercise_equipment junction for machines only. Infer load_mode from WorkoutX equipment field mapping.
- 🟠 **Line 394 in seed_workoutx endpoint** — 의존: `Equipment.is_freeweight filter for freeweight exercise identification`
  - 깨짐: Line 394: WHERE Equipment.is_freeweight==True used to filter default equipment for freeweight exercises. Column DROP causes WHERE clause AttributeError. Seed endpoint fails, database cannot be populated with exercises.
  - 수정: Replace with Equipment.equipment_type IN ('barbell','dumbbell','bodyweight') or exercise.load_mode-based filtering.
- 🟠 **Admin API seed-workoutx endpoint, lines 390-401** — 의존: `Line 394: filters Equipment.is_freeweight==True. Comments reference default_equipment_id and movement_label_en`
  - 깨짐: is_freeweight GENERATED column is removed (D6). Comment documents old implementation using default_equipment_id (still used at lines 429-430) which is being removed. Seed logic will fail when trying to write to removed column.
  - 수정: Update admin endpoint to filter on exercises.load_mode instead of Equipment.is_freeweight. Verify that default_equipment_id assignment logic is updated or removed per redesign spec. Update docstring and comments to reflect new schema.
- 🟠 **Lines 407-420 (equipment type mapping in seed function)** — 의존: `WorkoutX equipment field to load_mode enum mapping`
  - 깨짐: Lines 414, 418-419 use _WX_EQUIPMENT_TYPE dict to map WorkoutX equipment strings (barbell, dumbbell, bodyweight, machine, cable, cardio) to EquipmentType enum. This mapping becomes incomplete when new load_mode values (ez_barbell, trap_bar, kettlebell, band) are added to spec but _WX_EQUIPMENT_TYPE mapping not updated.
  - 수정: Expand _WX_EQUIPMENT_TYPE mapping to include new load_mode enum values. Add mappings for ez_barbell, trap_bar, kettlebell, band to seed script.

### `load_calc.py` (5)
- 🔴 **calculate_effective_weight function, lines 11-39** — 의존: `equipment_type parameter signature and match expression at lines 22-39`
  - 깨짐: Function accepts equipment_type enum values (cable|machine|barbell|dumbbell|bodyweight) but redesign requires load_mode (10 values including ez_barbell, trap_bar, kettlebell, band, cardio). Missing cases cause runtime fallthrough to ValidationError.
  - 수정: Update calculate_effective_weight signature to accept load_mode string parameter instead. Add new cases for ez_barbell (10kg bar), trap_bar (~20kg), kettlebell, band, cardio. Verify all call sites in routine_targets.py pass exercise.load_mode instead of Equipment.equipment_type.
- 🔴 **effective_to_stack_weight function, lines 54-68** — 의존: `equipment_type parameter used in match expression at line 65`
  - 깨짐: Function matches on equipment_type (cable|machine) to determine stack conversion. New load_mode taxonomy includes 10 values. Function must handle ez_barbell, trap_bar separately since bar weights differ. Currently does not handle these cases.
  - 수정: Update function to match on load_mode instead of equipment_type. Add explicit cases for barbell (20kg), ez_barbell (10kg), trap_bar (~20kg), dumbbell, kettlebell, band. Only cable/machine should return stack conversion. Update docstring with load_mode contract.
- 🟠 **Lines 11-39 calculate_effective_weight function signature** — 의존: `equipment_type parameter vs exercise.load_mode enumeration (spec D4 change)`
  - 깨짐: Spec D4 requires load_mode branching instead of equipment_type. Current function signature uses equipment_type. Callers must pass load_mode with extended enum values (barbell|ez_barbell|trap_bar|kettlebell|band|cardio). Function match cases incomplete for new values. Case mismatch raises ValidationError.
  - 수정: Change function signature to calculate_effective_weight(load_mode, ...). Update all match cases for barbell|ez_barbell|trap_bar|dumbbell|kettlebell|band|bodyweight|cable|machine|cardio.
- 🟠 **calculate_effective_weight() function, lines 22-39 (match statement on equipment_type)** — 의존: `equipment_type parameter values vs. exercise.load_mode new enum values`
  - 깨짐: Function accepts equipment_type parameter and uses match statement (lines 22-39) with cases: 'cable', 'machine', 'barbell', 'dumbbell', 'bodyweight'. Per spec, callers will pass exercise.load_mode with new values ('trap_bar', 'cardio', 'band', 'ez_barbell', 'kettlebell'). New values not in match cases will trigger '_' case, raising ValidationError.
  - 수정: Refactor function signature to accept load_mode instead of equipment_type. Add cases for new load_mode values: 'trap_bar' (20kg like barbell), 'cardio' (return 0), 'band' (like dumbbell), 'kettlebell', 'ez_barbell'. Update all callers to pass exercise.load_mode.
- 🟠 **Lines 22-39 (match statement equipment_type cases)** — 의존: `load_mode enum values addition (ez_barbell, trap_bar, kettlebell, band, cardio)`
  - 깨짐: Current case statement only handles: cable|machine|barbell|dumbbell|bodyweight. Spec adds ez_barbell, trap_bar, kettlebell, band, cardio. Case statement will raise ValidationError for unknown load_mode values.
  - 수정: Add cases for ez_barbell (bar_weight=10kg), trap_bar (bar_weight≈20kg), kettlebell (added weight), band (added weight), cardio (bodyweight fallback). Update all callers to use load_mode instead of equipment.equipment_type.

### `equipment.py` (4)
- 🔴 **_fetch_muscles function (lines 69-82)** — 의존: `EquipmentMuscle table (to be removed)`
  - 깨짐: Function at lines 74-76 queries EquipmentMuscle.equipment_id and joins MuscleGroup. Once equipment_muscles table is dropped, query fails with 'relation equipment_muscles does not exist'. Function is called by list_equipments endpoint (line 69 decorator is on _fetch_muscles helper).
  - 수정: Delete _fetch_muscles or refactor to query exercise_equipment + exercise_muscles instead. For machines without exercises, may need to add equipment_exercise cross-mapping table or deprecate primary_muscles field entirely.
- 🟠 **_fetch_muscles() lines 74-76** — 의존: `EquipmentMuscle model and table`
  - 깨짐: 라인 74-76 직접 확인: EquipmentMuscle 테이블 JOIN과 SELECT. 스펙 D5에서 equipment_muscles 테이블 제거되므로 테이블 미존재로 쿼리 실패.
  - 수정: Equipment → exercise_equipment → Exercise → exercise_muscles → MuscleGroup 경로로 리팩토링. 또는 equipment.primary_muscles 자체 삭제 가능 (근육 정보는 exercise 경로로만 제공).
- 🟠 **list_equipments endpoint (lines 98-150, beyond provided snippet)** — 의존: `EquipmentMuscle table via _fetch_muscles (lines 69-82)`
  - 깨짐: Endpoint queries equipment catalog. If it calls _fetch_muscles to populate primary_muscles, that query on EquipmentMuscle will fail post-migration. Complete endpoint implementation must be verified to confirm if primary_muscles field is fetched.
  - 수정: Verify if list_equipments calls _fetch_muscles. If yes, either replace with exercise_equipment junction or deprecate primary_muscles from EquipmentItem schema.
- 🟠 **Equipment API endpoints that query muscle relationships** — 의존: `EquipmentMuscle model/table used in muscle listing queries`
  - 깨짐: Code confirmed via grep uses '.join(EquipmentMuscle, EquipmentMuscle.equipment_id == Equipment.id)' to fetch equipment muscle mappings. After equipment_muscles table removal, query execution will fail with table-not-found error. This blocks equipment muscle listing endpoints.
  - 수정: Refactor endpoints to derive muscles from exercise_equipment→exercise_muscles join instead of direct equipment_muscles table. For machines only.

### `rag.py` (4)
- 🟠 **UserProfile dataclass lines 327-346, docstring lines 331-334** — 의존: `available_equipments field documents structure with source in (MACHINE|FREE). Docstring mentions equipment_muscles at line 334.`
  - 깨짐: Spec D5 removes equipment_muscles table. The MACHINE path documentation is outdated - machines now come from exercise_equipment N:M junction, not equipment_muscles. Documentation inconsistency causes confusion during implementation.
  - 수정: Update docstring to reflect new data sources: MACHINE items come from exercise_equipment junction (via exercises.name_en match), FREE items come from exercises with load_mode in baseline list. Remove reference to equipment_muscles from docstring.
- 🟠 **_build_routine_prompt function, lines 401-550** — 의존: `Lines 414-415: constructs [MACHINE]/[FREE] tags based on available_equipments source. Lines 452-456: equipment_label selection rule. Lines 508-509: prompts for equipment_label and equipment_type output.`
  - 깨짐: Spec §5 removes [MACHINE]/[FREE] tagging from prompts. Spec indicates prompt should output exercise-centric (exercise.load_mode and machine junction info) not equipment-label driven. Current prompt structure assumes equipment labels are the primary contract but redesign shifts to exercise-centric contract.
  - 수정: Simplify available_equipments structure to remove [MACHINE]/[FREE] tags. Update prompt JSON schema to request exercise name instead of equipment_label. Remove equipment_label selection rules. Add load_mode information to prompt for clarity. Update rules section to specify which load_modes are baseline vs machine-filtered.
- 🟠 **Lines 413-415 (tag assignment in _build_routine_prompt)** — 의존: `Equipment classification via is_freeweight and dual-path source tagging`
  - 깨짐: Line 414 assigns tag based on eq.get('source') which comes from 'MACHINE' or 'FREE' tags populated by dual-path machine_stmt/free_stmt in _build_rag_profile. Single-query architecture removes source classification.
  - 수정: Classify equipments by exercise.load_mode field instead. Load_mode in baseline list → [FREE], otherwise [MACHINE]. Update available_equipments construction in _build_rag_profile to add source tags.
- 🟡 **Lines 330-335 UserProfile docstring** — 의존: `available_equipments field description referencing is_freeweight/MACHINE/FREE distinction`
  - 깨짐: Docstring states 'MACHINE: equipments(is_freeweight=false)' but is_freeweight is dropped. No direct mapping for source MACHINE|FREE generation logic. Docstring becomes inaccurate, causes future maintainer confusion.
  - 수정: Update docstring: 'source: MACHINE(gym_equipments + equipment_type IN cable|machine) | FREE(exercise.load_mode IN freeweight_types)'

### `__init__.py` (3)
- 🔴 **Model exports section** — 의존: `ExerciseEquipmentMap class exported from app.models module`
  - 깨짐: When ExerciseEquipmentMap class is deleted per confirmed findings, any import statements like 'from app.models import ExerciseEquipmentMap' will fail with ImportError at module load time.
  - 수정: Remove ExerciseEquipmentMap from app/models/__init__.py exports. Update any code importing this class to use new ExerciseEquipment model instead.
- 🟠 **Lines 5, 14, 80, 83** — 의존: `ExerciseEquipmentMap and EquipmentMuscle imports and exports in __all__`
  - 깨짐: Attempting to import deprecated models after migration will fail. Module load will fail, cascading to all dependent modules (gyms.py, routines.py, seed.py).
  - 수정: Remove ExerciseEquipmentMap and EquipmentMuscle from imports and __all__ exports.
- 🟡 **Package-level model exports** — 의존: `ExerciseEquipmentMap and EquipmentMuscle in __all__ export list`
  - 깨짐: Package __init__.py exports both models in __all__: 'ExerciseEquipmentMap', 'EquipmentMuscle'. After model deletion from gym.py/exercise.py, import statement 'from app.models import ExerciseEquipmentMap' or 'from app.models import EquipmentMuscle' will fail with ImportError if any downstream code tries to import. This blocks any code path attempting to use these models.
  - 수정: Remove both model names from __all__ export list after model deletion. Verify no downstream imports exist in tests or other modules.

### `routine.py` (3)
- 🔴 **RoutineExercise class, lines 92-94** — 의존: `routine_exercises.equipment_id NOT NULL constraint (current) -> nullable (spec D7 requirement)`
  - 깨짐: Spec D7 requires equipment_id to be nullable for freeweight exercises. Current ORM enforces Mapped[uuid.UUID] (NOT NULL). Insertion of freeweight exercises will violate DB constraint.
  - 수정: Change RoutineExercise.equipment_id to Mapped[uuid.UUID | None] with mapped_column(nullable=True).
- 🔴 **RoutineExercise model, lines 92-94 (equipment_id NOT NULL constraint)** — 의존: `equipment_id field mapped as NOT NULL at line 92-93 with RESTRICT FK constraint`
  - 깨짐: Spec D7 makes equipment_id nullable for freweight exercises. Current model enforces NOT NULL at database level. Schema migration allows NULL but ORM constraint rejects NULL values, creating data integrity violation.
  - 수정: Change line 92 to make equipment_id nullable: equipment_id: Mapped[uuid.UUID | None]. Update FK ondelete from RESTRICT to SET NULL. Add docstring explaining NULL for freweight exercises.
- 🔴 **RoutineExercise class (lines 92-93)** — 의존: `routine_exercises.equipment_id constraint (NOT NULL to nullable conversion needed)`
  - 깨짐: ORM constraint is NOT NULL RESTRICT but schema at routines.py line 68 allows nullable (equipment_id: str | None = None). After redesign, freeweight exercises will have NULL equipment_id. ORM must match schema. Without nullable=True, INSERT fails when equipment_id is NULL.
  - 수정: Change ORM to: equipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(...), nullable=True, ondelete='SET NULL'). Alembic migration must mark column nullable and set default=None.

### `exercises.py` (2)
- 🟡 **list_exercises() lines 61-62** — 의존: `Exercise.category`
  - 깨짐: 라인 62: Exercise.category == category 필터. 현재 seed 데이터가 구식 6개 카테고리(chest/back/shoulders/arms/core/legs). 스펙에서 20개 WorkoutX bodyPart로 변경. 필터링 쿼리가 no-match 반환.
  - 수정: migration 시 Exercise.category seed 업데이트 (WorkoutX bodyPart 20개로). enum 제약 추가 권장. 또는 category 칼럼 자체 제거 가능.
- 🟡 **Line 62 (searchExercises function)** — 의존: `Exercise.category field taxonomy change to WorkoutX bodyPart enum`
  - 깨짐: Query filters Exercise.category == category param. Taxonomy changes from 6 anatomical regions to WorkoutX bodyPart values (chest/back/shoulder/legs/arms/abs/core). Frontend must send correct enum values or query returns 0 rows.
  - 수정: Verify Exercise.category field is validated to only accept WorkoutX bodyPart enum values. Add API documentation clarifying expected category parameter values.

### `routine_targets.py` (2)
- 🔴 **recommended_weight_kg function, line 137** — 의존: `Calls effective_to_stack_weight(mid, equipment_type or '', ...) passing Equipment.equipment_type`
  - 깨짐: After redesign, equipment_type parameter is deprecated in load_calc. Function receives Equipment.equipment_type but must receive Exercise.load_mode instead. Parameter name stays equipment_type but semantics change completely.
  - 수정: Change parameter name and semantics from equipment_type to load_mode. Update call signature at line 137 to extract load_mode from exercise (requires passing Exercise object in addition to Equipment). Add validation that load_mode is not None before calling effective_to_stack_weight.
- 🟠 **Lines 136-137 (effective_to_stack_weight call)** — 의존: `equipment_type parameter vs load_mode field relocation`
  - 깨짐: Line 137 calls effective_to_stack_weight with equipment_type param derived from session context. After redesign, should use exercise.load_mode for freeweight exercises. Callers in sessions.py and other modules need updating.
  - 수정: Add load_mode parameter path to routine_targets functions. For exercises, use load_mode; for equipment machines, use equipment_type. Update all callers (sessions.py lines 225, 528, 532).

### `seed.py` (2)
- 🔴 **Lines 21-30 imports, lines 530-537 ExerciseEquipmentMap writes** — 의존: `exercise_equipment_map table and ExerciseEquipmentMap model (deprecated)`
  - 깨짐: Line 26: imports ExerciseEquipmentMap. Lines 530-537: create ExerciseEquipmentMap records for exercise-equipment mappings. Table will be dropped post-migration. INSERT will fail. Entire seed script cannot complete.
  - 수정: Remove ExerciseEquipmentMap import and writes. Set Exercise.load_mode values and create exercise_equipment N:M records for machines only.
- 🔴 **seed() function, lines 525-537** — 의존: `exercise_equipment_map table + ExerciseEquipmentMap model (to be removed)`
  - 깨짐: Lines 528-537 construct and execute 'session.add(ExerciseEquipmentMap(exercise_id=ex_id, equipment_id=eq_id))' for all exercises. After model/table removal, model-not-found or table-not-found error will occur.
  - 수정: For freeweight exercises, set Exercise.load_mode and default_equipment_id. For machines, write to new exercise_equipment table. Replace lines 525-537 with conditional logic based on equipment type.

### `sessions.py` (2)
- 🟠 **_create_po_notifications() line 225** — 의존: `Equipment.equipment_type`
  - 깨짐: 라인 225: equipment.equipment_type 읽음. 스펙 D7에서 freeweight는 routine_exercises.equipment_id = NULL이 되므로 equipment 객체 자체 없음. equipment_type = None → po.calculate_increase(category=None) 호출로 실패 또는 잘못된 분기.
  - 수정: freeweight의 경우(rex.equipment_id=NULL) Exercise.load_mode 사용. 머신의 경우만 equipment.equipment_type 사용. 조건부 로직: if rex.equipment_id: category = str(equipment.equipment_type) else: category = str(exercise.load_mode)
- 🟠 **_check_and_create_po_notifications() lines 523-529** — 의존: `Equipment.equipment_type`
  - 깨짐: 라인 523: equipment_type = 'barbell' 기본값 설정. 하지만 freeweight의 equipment_id=NULL이면 equipment 조회 실패, equipment_type=None. 기본값을 'barbell'로 하면 spec violation (load_mode 사용해야 함).
  - 수정: Exercise.load_mode 조회 추가. rex.equipment_id=NULL인 경우 load_mode 사용: equipment_type = str(exercise.load_mode if not rex.equipment_id else equipment.equipment_type)

### `test_gym_muscle_equipments.py` (2)
- 🟠 **lines 257-280 (test_machine_label_falls_back_to_name)** — 의존: `movement_label_ko fallback logic verification (line 260: row.movement_label_ko=None)`
  - 깨짐: Test verifies movement_label_ko=None → name fallback behavior. Spec removes movement_label_ko. Test's fallback logic contract invalid upon implementation. Currently passing via mock.
  - 수정: Upon spec implementation: Remove test or rewrite to exercise-name-based labeling. Equipment label determination changes fundamentally from equipment properties to exercise names.
- 🟡 **lines 71-101 (_machine_row, _fw_row helpers)** — 의존: `movement_label_ko mock (line 80) + equipment_type (line 82, 100)`
  - 깨짐: Helpers mock movement_label_ko which spec removes. Mock-based tests currently pass, but helper design becomes obsolete when production redesigns for load_mode classification.
  - 수정: Upon spec implementation: Redesign _machine_row to use exercise.load_mode. Remove movement_label_ko mock. Update _fw_row to reflect load_mode-based classification.

### `test_routines.py` (2)
- 🔴 **lines 440-479 (test_swap_exercise_auto_picks_equipment)** — 의존: `pick_row.default_equipment_id setting (line 452) for freeweight equipment selection`
  - 깨짐: Test simulates Exercise with default_equipment_id to verify automatic equipment picking. Spec removes default_equipment_id. Test assumption (Exercise → equipment_id relationship) invalid upon implementation.
  - 수정: Upon spec implementation: Add load_mode='barbell' to pick_row. Remove default_equipment_id reference. Equipment selection via load_mode classification.
- 🔴 **lines 482-511 (test_swap_exercise_no_usable_equipment_returns_409)** — 의존: `pick_row.default_equipment_id=None (line 494) for machine exercise + movement_label_en matching assumption (line 501 comment)`
  - 깨짐: Test uses dual-path logic (default_equipment_id determines machine vs freeweight). Spec removes dual-path + default_equipment_id. Test's conditional logic (None → machine, value → freeweight) invalid upon implementation.
  - 수정: Upon spec implementation: Use load_mode='machine' classification. Exercise_equipment junction query instead of movement_label_en matching. Redesign equipment availability check.

### `20260604_equipment_centric_pr1.py` (1)
- 🟠 **downgrade() function migration rollback path** — 의존: `Downgrade consistency between Exercise.load_mode addition (PR-5) and column removal (PR-1 downgrade)`
  - 깨짐: If PR-5 migration (adding Exercise.load_mode) is applied, then someone downgrades back through PR-1, the downgrade() function will drop movement_label_en/ko/is_freeweight columns but will NOT migrate Exercise.load_mode back to default_equipment_id + is_freeweight classification. This leaves Exercise.load_mode orphaned and breaks the transition contract between PR-4.5 and PR-1 downgrades.
  - 수정: Add downgrade logic to migrate Exercise.load_mode back to default_equipment_id field values + is_freeweight computed column classification before executing column DROP statements.

### `20260604_seed_freeweight_exercises.py` (1)
- 🔴 **upgrade() function, exercise_equipment_map INSERT block (full migration)** — 의존: `exercise_equipment_map table (to be removed in PR-5)`
  - 깨짐: Migration docstring (lines 1-20) explicitly states purpose: 'exercise_equipment_map 자동 생성' (auto-generation). Migration code contains INSERT statements into exercise_equipment_map table. After table removal, migration execution will fail with table-not-found error.
  - 수정: Rewrite migration to INSERT into exercise_equipment (for machines) and set Exercise.load_mode for freeweight exercises via UPDATE statements instead.

### `20260604_seed_machine_movement_templates.py` (1)
- 🔴 **upgrade() SQL block, lines 81-250 (movement_label_en/movement_label_ko UPDATE statements)** — 의존: `equipments.movement_label_en, equipments.movement_label_ko columns (to be removed)`
  - 깨짐: Lines 81-250 contain _EQUIPMENT_LABEL_MAP tuples with movement_label_en/ko values. Migration executes UPDATE statements populating these columns. After column removal, UPDATE will fail with column-not-found error.
  - 수정: Replace movement_label updates with INSERT into exercise_equipment table. Join exercises by name_en to derive exercise_id, then link via exercise_equipment junction.

### `20260605_eqmuscle_deficit_backfill.py` (1)
- 🟠 **upgrade() function, SQL JOIN condition at line 44** — 의존: `equipments.movement_label_en column (to be removed)`
  - 깨짐: Line 44 executes 'JOIN exercises ex ON lower(ex.name_en) = lower(e.movement_label_en)'. After column removal, column-not-found error occurs at query execution time.
  - 수정: Post-redesign, this backfill is obsolete because equipment_muscles table is also removed. If backfill logic is still needed, refactor to JOIN via exercise_equipment table instead.

### `gen_freeweight_seed.py` (1)
- 🔴 **main() function, line 220 (exercise_equipment_map list initialization) + lines 274-275 (append to list)** — 의존: `exercise_equipment_map table structure, ExerciseEquipmentMap model`
  - 깨짐: Script generates migration code that creates exercise_equipment_map list (line 220) and populates it with (name_en, equipment_uuid) tuples (lines 274-275). Generated migration 20260604_seed_freeweight_exercises.py will contain INSERT statements targeting exercise_equipment_map table which will not exist post-redesign.
  - 수정: Rewrite generator to output Exercise.load_mode values (barbell/dumbbell/etc.) instead of equipment_map rows. For machine exercises, generate exercise_equipment junction rows with proper structure.

### `seed_exercises_workoutx.py` (1)
- 🔴 **upsert_equipment_map() function, lines 140-178** — 의존: `exercise_equipment_map table + ExerciseEquipmentMap model (to be removed)`
  - 깨짐: Function executes pg_insert(ExerciseEquipmentMap) at lines 168-176 for all equipment types from WorkoutX API. After schema removal, table-not-found or model-not-found error will occur during import/execution.
  - 수정: Replace ExerciseEquipmentMap writes with new exercise_equipment N:M writes for machines only. Update WORKOUTX_EQUIPMENT_TO_TYPE mapping to output load_mode enum values instead of equipment_type strings.

### `users.py` (1)
- 🟡 **_equipment_to_dto() line 387** — 의존: `Equipment.category enum values`
  - 깨짐: 라인 387: Equipment.category를 문자열로 변환. 현재 enum이 chest/back/shoulders/arms/core/legs 같은 구식 값(6개). 스펙 D6에서 WorkoutX bodyPart로 변경 (chest/back/shoulders/upper arms/lower arms/forearms/..., 20개). seed 후 enum 값 불일치 → validation error 또는 silent null handling.
  - 수정: EquipmentBodyCategory enum을 WorkoutX bodyPart 20개 값으로 업데이트. 또는 Equipment.category 자체 제거 (근육은 exercise 경로로만 제공).