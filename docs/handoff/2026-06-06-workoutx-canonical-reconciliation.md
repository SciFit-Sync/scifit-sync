# WorkoutX 캐노니컬 전환 + 클린슬레이트 재시드 — 종합 정리

> 작성 2026-06-06 · prod(hnwegx) 실측 + 전체 마이그레이션/시드 감사 기반
> 결정 방향: **WorkoutX 원본 분류를 캐노니컬 표준으로 채택** + **논문 제외 데이터 클린슬레이트 재시드**
> 정합성 우선순위(사용자 지정): ① DB↔데이터 ② DB↔백엔드 ③ DB↔프론트엔드

---

## 0. TL;DR

1. **분류 전환**: 앱 6부위/해부학 26근육 → **WorkoutX bodyPart(10)/target+secondary(~19)**. **DB 스키마 변경 불필요**(category/body_region/involvement/equipment_type 전부 `native_enum=False` = varchar). Python StrEnum 값 + 코드 + 데이터만 변경.
2. **진행된 데이터 PR 대부분 폐기**: #287/#284/#283 + 이 브랜치(default-remap)는 전부 **해부학 기준**이라 WorkoutX 클린슬레이트가 대체. **#281(루틴 품질)만 독립 유지.** activation% 수치·curated-72는 salvage.
3. **WorkoutX 재수집 필수**: 원본(bodyPart/target/secondaryMuscles/equipment)이 repo에 **캐시 안 됨**. 현재 시드 스크립트는 `target`/`equipment`만 쓰고 `bodyPart`·`secondaryMuscles`는 **버림**. → 시드 스크립트 재작성 + API 재수집.
4. **클린슬레이트 = 재설계와 통합**: 어차피 새로 시드하므로 **운동-중심 새 스키마로 직접 시드** → 이전에 합의한 "carry-over 마이그레이션" 불요. cleanup+restructure가 한 사건으로 합쳐짐.
5. **트레이드오프**: WorkoutX target은 해부학보다 **거침**(delts=삼각근 1개 vs 전/측/후 3개). 근육 해상도 손실 ↔ 데이터 완전성/일관성 획득.

---

## 1. 분류 체계 전환 — 스키마 비용 분석

| 컬럼 | 현재 타입 | WorkoutX 수용 비용 |
|---|---|---|
| `exercises.category` | `String(50)` 자유 varchar | **0** (이미 'upper arms' 등 수용 중) |
| `muscle_groups.name` / `body_region` | `String(50)` 자유 varchar | **0** (단 name·name_ko 둘 다 UNIQUE) |
| `equipments.category` | `EquipmentBodyCategory` enum, **`native_enum=False`** | **0** (DB는 varchar, Python enum 값만 확장) |
| `equipment_type` | `EquipmentType` enum, `native_enum=False` | **0** (변경 불요, WorkoutX equipment→type 매핑은 유지) |
| `exercise_muscles.involvement` | `MuscleInvolvement{primary,secondary,stabilizer}` | **0** (stabilizer 이미 enum 포함 — §검수에서 "위반"이라 한 건 내 스펙 오류) |

→ **DB 마이그레이션 없이** Python `EquipmentBodyCategory` StrEnum을 WorkoutX bodyPart로 교체하고, 데이터를 WorkoutX 값으로 시드하면 됨.

### WorkoutX 표준 어휘 (채택 대상)
- **bodyPart(10)** = category/body_region: `back, cardio, chest, lower arms, lower legs, neck, shoulders, upper arms, upper legs, waist`
- **target+secondaryMuscles(~19)** = muscle_groups: `abductors, abs, adductors, biceps, calves, cardiovascular system, delts, forearms, glutes, hamstrings, lats, levator scapulae, pectorals, quads, serratus anterior, spine, traps, triceps, upper back`
- **involvement**: `target → primary`, `secondaryMuscles[] → secondary`
- **equipment**: WorkoutX `equipment` 문자열 → `default_equipment_id` / equipment_type

---

## 2. 진행된 PR 작업 reconciliation ("전부 확인")

| PR / 브랜치 | 내용 | taxonomy | 클린슬레이트 후 처분 |
|---|---|---|---|
| **#281** routine-arm-target | `_SETS_BY_GOAL`, `_allocate_priority_slots` (루틴 품질) | 무관(코드) | ✅ **유지** — 데이터와 독립 |
| **#283** prod-migration-drift-recovery | `recover_default_equip_bodyweight` (garbage default 복구) | 해부학/garbage | ❌ **폐기** — 재시드엔 garbage 없음 |
| **#284** arm-equipment-muscles-fix | `fix_arm_equipment_muscles` (팔 3기구 교정) | 해부학 | ❌ **폐기** — equipment_muscles는 운동에서 파생 |
| **#287** ① normalize_muscle_groups | 26 해부학 그룹 정규화 | **해부학(정반대)** | ❌ **폐기** — WorkoutX 19로 재시드 |
| **#287** ② seed_muscle_activation | 1355운동 exercise_muscles + activation% | 해부학 | ⚠️ **수치만 salvage** (아래) |
| **#287** ③ eqmuscle_deficit_backfill | arms 결손 백필 | 해부학 | ❌ 폐기 |
| **#287** ④ latpulldown_secondary | 랫풀다운 보조근 | 해부학 | ❌ 폐기 |
| **#287** ⑤ dipchin_compound | Dip/Chin 복합 | 해부학 | ❌ 폐기 |
| **이 브랜치** default-equipment-remap | 553 default 오배정 정정 | garbage 특정 | ❌ **폐기** — 재시드가 default를 WorkoutX equipment로 새로 채움 |
| **PR-5** eem DROP | exercise_equipment_map 제거 | — | 🔄 재설계로 흡수(머신↔동작 정션 repurpose) |

### Salvage 대상 (버리지 말 것)
- `muscle_activation_seed.csv` (3893행, 1355운동, 26 해부학 근육, activation_pct 빈값 0) — **% 수치는 Gemini EMG라 재사용 가치 높음.** 해부학→WorkoutX 병합 맵(§2.1)으로 salvage.
- `curated-72-final-mapping.csv` (팀 수동검증 72운동) — 재사용.
- ⚠️ **WorkoutX 번역 규칙(workoutx-muscle-mapping-gaps)의 미결 결정(Upper Back 능형/승모, delts 기본)은 WorkoutX 원본 유지 시 소멸** — 번역을 안 하니 규칙 불요. (§J 게이트 결정 사라짐)

### 2.1 activation% 병합 맵 (해부학 26 → WorkoutX 19) — 확정

> ✅ **결정: WorkoutX로 통일** (2026-06-06). activation% 수치는 버리지 않고 아래 맵으로 WorkoutX 해상도에 병합.

WorkoutX 캐노니컬 근육 어휘(~19): `abs, abductors, adductors, biceps, calves, cardiovascular system, delts, forearms, glutes, hamstrings, lats, levator scapulae, pectorals, quads, serratus anterior, spine, traps, triceps, upper back`

| WorkoutX | ← 해부학 seed slug | 병합 |
|---|---|---|
| `delts` | anterior_deltoid + lateral_deltoid + posterior_deltoid | 3→1, **MAX %** |
| `pectorals` | pectoralis_major + pectoralis_minor | 2→1, MAX |
| `glutes` | gluteus_maximus + gluteus_medius | 2→1, MAX |
| `abs` | rectus_abdominis + obliques + transverse_abdominis | 3→1, MAX |
| `upper back` | rhomboids | 1:1 |
| `spine` | erector_spinae | 1:1 |
| `lats` | latissimus_dorsi | 1:1 |
| `traps` | trapezius | 1:1 |
| `biceps` | biceps_brachii (+brachialis) | brachialis 흡수 |
| `triceps` | triceps_brachii | 1:1 |
| `forearms` | forearms | 1:1 |
| `quads` | quadriceps | 1:1 |
| `hamstrings` / `calves` / `adductors` / `serratus anterior` / `levator scapulae` | 동명 | 1:1 |
| (drop) | rotator_cuff(→delts), hip_flexors(drop) | 소수(7/79행) |

**병합 규칙**: N→1 시 `activation_pct = MAX`, `role = primary 우선`(하나라도 primary면 primary).
**activation% 없는 (exercise, WorkoutX muscle)** = NULL (필요 시 Gemini 추가 산출).

---

## 3. 데이터 가용성 갭 — WorkoutX 재수집 필수

- `mlops/scripts/seed_exercises_workoutx.py`는 WorkoutX API에서 **라이브 fetch** (캐시 없음). `X-WorkoutX-Key` 헤더, wx_ 키.
- 현재 수집 필드: `name`, `target`, `gifUrl`, `equipment` 만. **`bodyPart`·`secondaryMuscles` 미수집·미저장.**
- 현재 변환: `WORKOUTX_TARGET_TO_CATEGORY`(target→6부위), `WORKOUTX_EQUIPMENT_TO_TYPE`(equipment→type). → WorkoutX 원본 유지 시 **target→category 변환 제거**, 대신 `bodyPart→category` 직접 저장 + `target→primary muscle` + `secondaryMuscles→secondary` 저장하도록 **재작성**.
- 전제 확인 필요: **WorkoutX API 키 유효 + secondaryMuscles 필드 제공 여부.**

---

## 4. 클린슬레이트 재시드 계획 (사용자 제안)

### 4.1 무엇을 초기화 / 보존
| 대상 | 처리 | 비고 |
|---|---|---|
| 논문: `papers`, `paper_chunks`, ChromaDB | **보존** | 재수집 비쌈, 손대지 않음 |
| 레퍼런스: `muscle_groups`, `exercises`, `exercise_muscles`, `equipments`, `equipment_muscles`, `gym_equipments`, `exercise_equipment_map` | **초기화 → 재시드** | WorkoutX 기준으로 |
| gym: `gyms`, `user_gyms` | **선별** | 실 헬스장(더찬스짐/대니스짐)은 재시드, 테스트 gym 제외 |
| 사용자: `workout_routines`, `routine_*`, `workout_logs`, `user_exercise_1rm` | **결정 필요** | 아래 4.2 |

### 4.2 🔴 FK 영향 + 결정 필요 (파괴적 — 백업+허가 게이트)
- exercises/equipments를 비우면 **이들을 FK로 참조하는** `routine_exercises`, `workout_log_sets`, `user_exercise_1rm`, `routine_papers`가 깨짐.
- **결정**: pre-launch(루틴 16~20, blast≈0)이므로 사용자 루틴/기록도 **함께 초기화**하는 게 단순. 단 이건 사용자 데이터 → **명시 허가 필요**.
- **백업**: 방금 `docs/handoff/db-export/*.csv`로 현재 prod 전체를 덤프함 = 백업 확보됨. 초기화 전 한 번 더 타임스탬프 스냅샷 권장.
- ⚠️ CLAUDE.md: TRUNCATE/DELETE는 절대금지 대상 → **반드시 Alembic 멱등 마이그레이션** + 백업 확인 후.

### 4.3 함정 — "alembic 그대로 재실행"은 안 됨
기존 시드 마이그(`20260525_seed_muscle_groups_exercises`, `seed_freeweight`, `machine_templates`, `eqmuscle_direct`, `normalize`, `seed_activation`)는 **전부 해부학 기준**. 그대로 재실행하면 해부학으로 다시 채워짐.
→ **시드 마이그레이션을 WorkoutX 기준으로 재작성**해야 함. 이게 클린슬레이트 작업의 본체.

---

## 5. 우선순위 3단계 정렬 (사용자 지정)

### ① DB ↔ 데이터 정합성 (최우선)
- 클린슬레이트 재시드: WorkoutX 원본으로 muscle_groups(19) / exercises(category=bodyPart) / exercise_muscles(target+secondary) / equipments / equipment_muscles(운동에서 파생) / default_equipment_id(equipment) 일괄 시드.
- 게이트: primary 결손 0(유산소 제외), default garbage 0, 기구 primary 과다 0, 테스트 gym 제외, generic 중복 0.

### ② DB ↔ 백엔드 정합성
- Python `EquipmentBodyCategory` StrEnum → WorkoutX bodyPart 값으로 교체.
- `routines.py` `_REGION_ALIASES` / `_BODY_PART_KO` → WorkoutX bodyPart 어휘로.
- `rag.py` 프롬프트 부위/근육 표현 정합.
- `load_calc` 영향 점검(equipment_type 기준은 불변).
- 테스트(load_calc/po/rag 100% 커버리지) 갱신.

### ③ DB ↔ 프론트엔드 정합성
- 부위 선택 UI(챗봇/루틴 생성)가 WorkoutX bodyPart 10종을 쓰도록.
- 근육 활성도 표시·1RM dot 색상 등 근육 어휘 정합.

---

## 6. 재설계와의 통합 (중요)

클린슬레이트면 이전에 합의한 **"정리 먼저 → 구조 carry-over"의 carry-over가 불요**해짐 — 새 데이터를 어차피 넣으니 **운동-중심 최종 스키마로 직접 시드**.
→ 권장 순서: **(a) 최종 스키마 확정**(load_mode on exercise, 머신↔동작 정션=eem repurpose, movement_label 제거, WorkoutX taxonomy) → **(b) WorkoutX 기준 시드 마이그 재작성** → **(c) 초기화+재시드** → **(d) 백엔드 정합) → (e) 프론트 정합)**.

---

## 7. 트레이드오프 — 근육 해상도

WorkoutX target은 해부학보다 거침:
- `delts` 1개 ↔ 앱 전/측/후 삼각근 3개
- `abs` 1개 ↔ 복직근/복사근/복횡근
- `glutes` ↔ 대둔근/중둔근

→ 부위 선택·필터엔 충분하나, "전면 삼각근 활성도 %" 같은 **세밀 표시·1RM dot 일부는 해상도 하락**. secondaryMuscles로 일부 보완 가능. **수용 가능 판단**(현재 95% 운동이 근육 0개라 완전성이 우선).

---

## 8. 잠가야 할 결정 (브레인스토밍 게이트)

1. **사용자 데이터(routines/logs/1rm) 초기화 동의?** (pre-launch, 함께 wipe가 단순) — 🔴 파괴적, 명시 허가 필요.
2. **WorkoutX API 키 유효 + secondaryMuscles 제공?** (재수집 전제 — 확인 필요)
3. **재설계(운동-중심 새 스키마)를 클린슬레이트에 통합?** (권장 = 통합, carry-over 제거)
4. **activation% salvage 시 deltoid 3→delts 1 병합 규칙** (max? 평균? primary 우선?)
5. **equipments.category도 WorkoutX bodyPart로?** (운동과 통일 vs 기구는 6부위 유지) — 통일 권장

---

## 9. 참조
- `2026-06-06-db-cleanup-inventory.md` — 현 prod 더티데이터 (해부학 기준, 이 문서가 일부 대체)
- `2026-06-06-table-population-spec.md` — ⚠️ **해부학 기준이라 폐기 예정** (WorkoutX 기준 신 spec 필요)
- `db-export/*.csv` — 현 prod 전체 덤프(백업)
- `2026-06-05-workoutx-1283-mapping.csv` / `curated-72-final-mapping.csv` — salvage 후보
- 메모리: `project_workoutx_freeweight_sourcing`, `project_equipment_centric_pr_chain`, `project_activation_pct_prod_state`
