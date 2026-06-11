# 운동–기구 재설계 (WorkoutX 캐노니컬) — 설계 스펙

> 작성 2026-06-06 · 상태: **구현 완료 (2026-06-07, PR #297/#300 + 20260606~07 마이그레이션 3종, prod 반영)** · prod(hnwegx) 실측 + WorkoutX 실 API 1324운동 기반
> 한 줄: **운동-중심 + 기구↔운동 N:M + 프리웨이트 baseline + WorkoutX 분류 통일 + 클린슬레이트 재시드**

---

## 0. 목표

1. **기구 ↔ 운동 N:M** — 케이블 1대가 여러 동작, 한 동작이 여러 머신.
2. **프리웨이트/맨몸 = 전 헬스장 baseline** — gym 등록 없이 항상 가용. 분류는 운동이 보유.
3. **WorkoutX 분류로 통일** — bodyPart/target/secondaryMuscles/equipment.
4. **데이터 정합성 최우선** — 더티 데이터(95% 무근육, 553 default 오배정, garbage primary) 클린슬레이트로 일소.
5. 정합성 우선순위: ① DB↔데이터 ② DB↔백엔드 ③ DB↔프론트.

## 1. 배경 — 현 prod 실측 (왜 재설계인가)

- exercise_muscles **147행, primary 보유 운동 69/1401** (95% 무근육) → 루틴 근육필터 무력 → "팔→전신" 버그.
- `equipment_muscles` garbage(한 기구 5~6 primary) → "팔에 랫풀다운".
- `default_equipment_id` **553 오배정**(EZ Bar 177 / Assisted 376) → load_calc 폭탄.
- exercises.category 혼재(6부위 + WorkoutX bodyPart), muscle_groups 드리프트.
- 근본 구조 결함: 머신 1:N을 `movement_label_en` 단수로 못 담음 / 분류가 FK(default_equipment_id)에 종속.
- ⚠️ pre-launch(루틴 16~20, blast≈0) → 클린슬레이트 안전.

## 2. 확정 결정 (decision log)

| # | 결정 |
|---|---|
| D1 | taxonomy = **WorkoutX** (bodyPart 10 / target 19+Hip Flexors=20 / equipment class) |
| D2 | **(B)** generic implement 행 제거. 프리웨이트는 equipment 행 없음, `exercises.load_mode`+load_calc 상수 |
| D3 | 기구↔운동 **N:M 정션 신규 `exercise_equipment`** (eem 폐기 후) |
| D4 | 프리웨이트/맨몸/풀업바/딥스대 = **baseline**(항상 가용), 머신만 gym 필터 |
| D5 | `equipment_muscles` **폐기** → 운동에서 파생 |
| D6 | `movement_label_en/ko`, `default_equipment_id`, `equipments.is_freeweight` **제거** |
| D7 | `routine_exercises.equipment_id` **NULL 허용**(프리웨이트=NULL) |
| D8 | EZ Barbell / Trap Bar = **별도 load_mode 유지** (bar 무게 다름) |
| D9 | activation% = 기존 해부학 시드(3893행) → 병합 맵으로 salvage(MAX, primary 우선) |
| D10 | 한글명(운동·근육) = Gemini 일괄 → 파일 → 사용자 검증 |
| D11 | **클린슬레이트 재시드**(논문 제외). wipe 범위는 D15로 확정 |
| D12 | 머신↔실물기구 매핑 = Gemini 판단 → 파일 → 사용자 검증 (실물 기구 적재 후) |
| **D13** | **`load_mode`에 `weighted` 독립 추가** (체중+외부부하 36개를 bodyweight와 분리; codex#1) |
| **D14** | **머신 선택 = (b)**: LLM이 운동선택 → 정션⋈gym으로 M' 도출, M'≥2면 LLM 택1. is_default 불필요 (§5) |
| **D15** | **wipe 범위 = 전체 wipe** (루틴+프로그램+workout_logs/log_sets/1rm + 레퍼런스). "루틴만"은 FK상 불가(codex#1/#2). users/chat/profile/논문 보존 |
| **D16** | **SOT 정리 = 관련 문서 업데이트**: database-schema.md·erd-v2.3·reconciliation·templates·api-exercise-swap를 본 스펙 기준으로 갱신/superseded (codex#1/#3) |

## 3. 목표 스키마 (before → after)

### exercises (동작)
```
유지: id, name(ko), name_en(UQ), description, gif_url
+ load_mode  enum-varchar: barbell|ez_barbell|trap_bar|dumbbell|bodyweight|weighted|
             kettlebell|band|cable|machine|cardio   (WorkoutX equipment→class, D13: weighted 독립)
  category   = WorkoutX bodyPart (varchar, 변경무)
- default_equipment_id   (제거 → 정션/load_mode 대체)
```

### equipments (실물 머신 only)
```
유지: id, brand_id, name, name_en, sub_category, equipment_type(cable|machine),
      pulley_ratio, bar_weight(+unit), has_weight_assist, min/max_stack, stack_weight, stack_unit, image_url
- generic implement 행 (Barbell/Dumbbell/Bodyweight/EZ/Trap/Olympic 등 placeholder) 전부 제거
- movement_label_en / movement_label_ko 제거
- is_freeweight (GENERATED) 제거   (분류는 exercises.load_mode가 보유)
- category(EquipmentBodyCategory) : 운동과 동일하게 WorkoutX bodyPart로 (또는 머신 분류용으로만)
```

### exercise_equipment (신규 N:M 정션, eem 폐기 후)
```
exercise_id  FK→exercises   (PK)
equipment_id FK→equipments  (PK)
source       'seed' | 'gemini'
confidence   numeric(3,2) NULL
* 머신 운동만 행 보유. 프리웨이트 운동 = 0행.
```

### muscle_groups (WorkoutX 20)
```
name = WorkoutX target+Hip Flexors (영문), name_ko = Gemini, body_region = WorkoutX bodyPart
20종: Abs, Pectorals, Biceps, Glutes, Delts, Triceps, Upper Back, Lats, Calves, Quads,
      Forearms, Cardiovascular System, Hamstrings, Spine, Traps, Adductors,
      Serratus Anterior, Abductors, Levator Scapulae, Hip Flexors
```

### exercise_muscles
```
exercise_id, muscle_group_id, involvement(primary|secondary), activation_pct
primary  = WorkoutX target (1:1 무번역)
secondary= WorkoutX secondaryMuscles → muscle_normalization.md 맵 (drop 5종 제외)
activation_pct = 병합 맵(reconciliation §2.1), 없으면 NULL
```

### equipment_muscles → **폐기** (머신 근육 = 정션 경유 exercise_muscles 파생)
### exercise_equipment_map(eem) → **폐기**
### gym_equipments → 유지 (gym ↔ 실물 머신만; 프리웨이트 미등록)
### routine_exercises → `equipment_id` **NULL 허용**

## 4. load_calc 변경 (`services/load_calc.py`)
- 분기 기준: `equipment.equipment_type` → **`exercise.load_mode`**
- 프리웨이트 상수: `barbell=20, ez_barbell=10, trap_bar≈20, dumbbell/kettlebell/band=added, bodyweight=bw(±), weighted=bw+added`
- cable/machine: `routine_exercises.equipment_id`(실물)의 pulley_ratio/stack/has_weight_assist 사용
- 100% 커버리지 테스트 갱신(load_mode 케이스).

## 5. 루틴 생성 변경 (`api/v1/routines.py` + `services/rag.py`)
**단일 가용성 규칙** (dual-path 제거):
```
운동 E 가용(gym G) ⟺
  E.primary 근육 ∈ 선택부위(exercise_muscles)
  AND ( E.load_mode ∈ {barbell,ez_barbell,trap_bar,dumbbell,bodyweight,weighted,kettlebell,band}  -- baseline 항상
        OR ∃ exercise_equipment(E, m) where m ∈ gym_equipments(G) )                              -- 머신
```
- `_build_rag_profile`: machine_stmt/free_stmt 통합 → 운동-중심 단일 쿼리.
- `rag.py _build_routine_prompt`: "equipment label" 계약 → **운동(exercise) 계약**으로. `[MACHINE]/[FREE]` 태깅 제거.
- `_resolve_label_to_ids`: 라벨→기구 → 운동→(load_mode/머신) 해석으로.

**머신 선택 의미론 (D14 = (b)):** LLM이 운동 선택 → `exercise_equipment ⋈ gym_equipments(G)`로 그 gym의 매칭 기구 M' 도출.
- 프리웨이트(load_mode∈baseline) → `equipment_id = NULL` (정션 무관, 항상 가용)
- 머신 운동 M'=0 → 후보 제외(그 gym 불가) / M'=1 → 자동 / **M'≥2 → LLM이 펼쳐진 (운동×기구) 후보에서 택1**
- is_default/display_rank 불필요. 후보가 (exercise_id, equipment_id) 쌍을 들고 있어 LLM 선택이 곧 결정적 해석.
- ⚠️ M'≥2 펼치기 시 "동일 동작·하드웨어만 다름 — 하나만" 프롬프트 명시(중복 처방 방지).

## 6. 데이터 소스 & 매핑 규칙

### WorkoutX 운동 객체 → 우리 테이블
| WorkoutX | → |
|---|---|
| name | exercises.name_en |
| bodyPart | exercises.category |
| equipment | exercises.load_mode (class 룩업) + 머신이면 정션 |
| target | exercise_muscles primary |
| secondaryMuscles[] | exercise_muscles secondary (정규화 맵) |
| gifUrl | exercises.gif_url |

### equipment(34) → load_mode class 룩업
주 토큰 기준: Barbell/Olympic→barbell, Ez Barbell→ez_barbell, Trap Bar→trap_bar, Dumbbell(+compound)→dumbbell, Body Weight(+variant)→bodyweight, **Weighted→weighted(D13, 별도)**, Kettlebell→kettlebell, Band/Resistance Band→band, Cable→cable, Leverage/Smith/Sled/Hammer/Assisted→machine, Elliptical/Bike/Skierg/Stepmill/Ergometer→cardio, Ball/Roller/Rope/Tire→bodyweight(accessory). **초안 후 사용자 검토.**
> ⚠️ codex#3: `mlops/scripts/seed_exercises_workoutx.py`의 `WORKOUTX_TARGET_TO_CATEGORY`(target→6부위)·`WORKOUTX_EQUIPMENT_TO_TYPE`(ez/trap→barbell 붕괴, kettlebell/band/cardio 누락)를 **재작성**: category=bodyPart 그대로, equipment→load_mode 11종 보존, 미지원값 skip 아닌 fail-fast.

### 근육 정규화 → `docs/handoff/workoutx-raw/muscle_normalization.md`
### 머신↔실물기구 N:M → Gemini 판단 + 검증 파일(실물 머신 기준). **실물 기구 적재 후 실행(§7 순서).**
### 한글 → Gemini 일괄(exercises.name 1401 + muscle name_ko 20) → 파일 → 검증
### activation% → `muscle_activation_seed.csv`(3893, 해부학26) → 병합 맵

## 7. 마이그레이션 & 데이터 이행 (클린슬레이트)

> 🔴 파괴적: 백업 확인(`db-export/*.csv` 확보됨) + Alembic 멱등. 직접 DELETE/대시보드 금지.

**순서:**
1. **스키마 변경** 마이그(load_mode 추가, exercise_equipment 신설, eem/equipment_muscles/movement_label/default_equipment_id/is_freeweight 제거, routine_exercises.equipment_id NULL 허용)
2. **초기화 (D15 = 전체 wipe)**: muscle_groups/exercises/exercise_muscles/equipments/gym_equipments/equipment_reports/equipment_suggestions + **routine 계열 + programs/program_routines + workout_logs/workout_log_sets/user_exercise_1rm 전량** wipe. **논문(papers/paper_chunks/Chroma)·users·chat·profile 보존.** FK 안전순서는 마이그 draft 참조.
3. **재시드 (WorkoutX 기준, 의존순)**:
   a. muscle_groups 20 (+name_ko)
   b. **실물 기구**(equipments) + gym_equipments  ← 머신 N:M 선결
   c. exercises (load_mode, category=bodyPart, gif) + exercise_muscles(target/secondary 정규화 + activation%)
   d. 프리웨이트: 정션 없음(load_mode만)
   e. **머신 정션**(exercise_equipment): Gemini 매핑 검증본 적재
4. **백엔드 정합**(enum/region맵/rag/load_calc) → **프론트 정합**(부위 UI)

**선결 확인**: 적용 전 백업(db-export 스냅샷). 전체 wipe라 0행 아니어도 진행하되 건수 로깅(마이그가 WARNING).

## 8. PR 처분
- ✅ 유지: **#281**(루틴 품질)
- ❌ 폐기: #287(해부학 normalize/activation), #284(arm fix), #283(default recover), 현 브랜치(default-remap)
- ⚠️ salvage: `muscle_activation_seed.csv`(activation% 수치, 병합), `curated-72`(검증 매핑)
- 🔄 PR-5(eem DROP) → 본 재설계가 eem 폐기로 흡수

## 9. 검증 게이트 (재시드 후 0건)
- primary 근육 결손 = 0 (cardio 제외)
- load_mode NULL = 0
- 머신 정션 없는 cable/machine 운동 = 0 (또는 알려진 잔존만)
- 테스트 gym 제외, gym_equipments orphan = 0
- load_calc/po/rag 테스트 100% pass

## 10. 미결 / 검증 필요
- WorkoutX `equipment` class 룩업 34종 초안 → 사용자 검토 (§6)
- Gemini 한글/머신매핑 산출물 → 사용자 검증
- `equipments.category`를 WorkoutX bodyPart로 통일할지 (머신 분류 용도) — 경미
- 실물 기구 데이터 소스 정본화(현 prod 머신 + 브랜드 CSV: hammer/panatta/newtech/chancegym)

## 참조
- `docs/handoff/2026-06-06-workoutx-canonical-reconciliation.md` (PR reconciliation + activation 병합 맵) (저장소 외부 산출물 — 정리됨)
- `docs/handoff/workoutx-raw/muscle_normalization.md` (근육 정규화 맵)
- `docs/handoff/workoutx-raw/exercises.json` (WorkoutX 원본 캐시 1324) (저장소 외부 산출물 — 정리됨)
- `docs/handoff/2026-06-06-db-cleanup-inventory.md` (현 prod 더티데이터) (저장소 외부 산출물 — 정리됨)
- `docs/handoff/db-export/*.csv` (현 prod 백업) (저장소 외부 산출물 — 정리됨)
