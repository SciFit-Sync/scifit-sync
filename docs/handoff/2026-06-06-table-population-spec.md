# 테이블 채움 스펙 (Population Spec / 검수 프롬프트)

> 작성 2026-06-06 · 대상 = **현재 prod(hnwegx) 스키마** (운동↔기구 재설계 *이전*)
> 용도: `docs/handoff/db-export/<table>.csv` 덤프를 **이 스펙과 대조**해 직접 결함을 찾기 위한 기준.
> 각 섹션은 LLM에 그대로 먹여 "이 테이블을 검수/채워라" 프롬프트로 써도 되도록 선언형으로 작성.
> 🔮 = 운동-중심 재설계로 바뀔 부분(현재 기준 검수엔 무관, 참고용).

값 표기 규칙: `enum{...}` = 허용값 고정, `FK→t` = 외래키, `NN` = NOT NULL, `UQ` = unique.

---

## muscle_groups — 근육군 마스터 (≈26행)

**역할**: 모든 근육의 표준 사전. exercise_muscles / equipment_muscles가 이걸 참조.

| 컬럼 | 의미 | 유효값/제약 |
|---|---|---|
| id | PK | uuid |
| name | 영문 표준 슬러그 | NN, UQ. 예: `latissimus_dorsi`, `biceps_brachii`, `pectoralis_major` |
| name_ko | 한글명 | NN, UQ. 예: `광배근`, `상완이두근` |
| body_region | 대분류 | NN, enum{`chest`,`back`,`shoulders`,`arms`,`core`,`legs`} |

**올바른 행 불변식**
- `name`은 snake_case 영문 슬러그, 사람 이름·임의 문자열 금지 (드리프트 흔적).
- `name`·`name_ko` 둘 다 유일.
- `body_region`은 위 6개 외 금지.

**흔한 결함 (검수 포인트)**
- ❌ 사람 이름 슬러그 8종 + `Upper Back` 같은 드리프트 → PR #287 `normalize_muscle_groups`가 26표준으로 교정 (배포 대기).
- ❌ name_ko 중복(가슴↔대흉근 등) — seed 충돌 흔적.

---

## exercises — 운동 마스터 (≈1,401행)

**역할**: 모든 동작(움직임). 루틴 생성의 프리웨이트 후보·근육 매핑·기구 매핑의 중심.

| 컬럼 | 의미 | 유효값/제약 |
|---|---|---|
| id | PK | uuid |
| name | 한글명 | NN |
| name_en | 영문명 | NN, **UQ** (라벨 해석 키) |
| description | 설명 | nullable |
| category | 대표 부위 | enum{`chest`,`back`,`shoulders`,`arms`,`core`,`legs`} = primary 근육의 body_region |
| gif_url | 시연 GIF | nullable (WorkoutX 소싱) |
| default_equipment_id | **구현 기구**(프리웨이트) | FK→equipments, nullable |

**올바른 행 불변식**
- `name_en` 유일. (중복 시 라벨 해석 깨짐)
- `category`는 그 운동의 primary 근육 부위와 일치해야 함 (예: Barbell Curl → `arms`).
- `default_equipment_id`는 **그 운동을 실제로 수행하는 implement**를 가리켜야 함:
  - 맨몸 운동 → Bodyweight generic(`57d1b189…`, assist=false)
  - 바벨 운동 → Barbell generic(`f970fcc9…`, 20kg)
  - 덤벨 운동 → Dumbbell generic(`a0b9376d…`)
  - 머신/Lever/treadmill 전용 → NULL (gym 보유 머신으로 런타임 폴백)
- 유산소(러닝/사이클 등 29개)는 근육 없음 — exercise_muscles 0행 허용(예외).

**흔한 결함 (검수 포인트) — `default_equipment_id` 컬럼 집중**
- 🔴 `default_equipment_id = 32f43f66…`(EZ Bar) 인데 **맨몸/일반 바벨** → 오배정. (177건; 단 curl/skullcrusher/french press 등 EZ바 isolation은 **정당**)
- 🔴 `default_equipment_id = c323aec6…`(Assisted Pull-up Machine, assist=true) 인데 **맨몸 운동** → 오배정 (376건). load_calc `body_weight − stack` 폭탄.
- ❌ 머신 전용 운동(`*lever*`, `hack squat`, `run` 등)인데 default 가 bodyweight/barbell → NULL이어야 함.
- ❌ `name_en` 빈 값/중복.
→ 상세·정정안: `2026-06-06-db-cleanup-inventory.md §2`, `2026-06-05-exercise-equipment-mislink-audit.md`.

🔮 재설계 후: `default_equipment_id` 제거 → 운동에 **`load_mode` enum{bodyweight,barbell,dumbbell,cable,machine}** 직접 보유. 머신 매핑은 정션으로.

---

## exercise_muscles — 운동↔근육 (운동당 N행)

**역할**: 운동이 자극하는 근육 + 강도. 루틴 생성 프리웨이트 **근육 필터의 진실원천**.

| 컬럼 | 의미 | 유효값/제약 |
|---|---|---|
| exercise_id | FK→exercises | NN (복합 PK) |
| muscle_group_id | FK→muscle_groups | NN (복합 PK) |
| involvement | 주/보조 | enum{`primary`,`secondary`} |
| activation_pct | EMG 활성도% | 0–100 또는 NULL |

**올바른 행 불변식**
- **모든 운동은 `primary` 근육 ≥ 1행** (유산소 29 예외).
- `muscle_group_id`는 muscle_groups에 실재 (orphan FK 금지).
- primary는 "주로 쓰는 근육"만 — isolation 운동이 primary 5개 같은 잡탕 금지.

**흔한 결함**
- ❌ primary 0건(결손) → 그 운동은 어떤 근육 필터에도 안 잡힘.
- ❌ WorkoutX 뭉뚱그림(어깨→삼각근 3분류 미상, Upper Back→능형/승모 미정) — 번역 규칙 미결(§J). 어깨 143·Upper Back 88.
- ❌ activation_pct 전부 NULL → 활성도 표시 0%. PR #287 `seed_muscle_activation`(3893행)이 채움.

🔮 재설계 후: 변화 없음(운동-중심의 핵심 테이블 그대로).

---

## equipments — 기구 마스터 (≈178행)

**역할**: 물리 기구 + 중량계산 파라미터. 머신은 movement_label_en으로 동작 표현(현재).

| 컬럼 | 의미 | 유효값/제약 |
|---|---|---|
| id | PK | uuid (seed generic은 **uuid5 결정적**) |
| brand_id | FK→equipment_brands | nullable |
| name | 한글명 | NN |
| name_en | 영문명 | nullable (결손 101) |
| category | 대표 부위 | enum{`chest`,`back`,`shoulders`,`arms`,`core`,`legs`} or NULL |
| sub_category | 세부 영역 | varchar, 자유어휘(예: `upper_back`,`triceps`) |
| equipment_type | 물리 타입 | NN, enum{`cable`,`machine`,`barbell`,`dumbbell`,`bodyweight`} |
| is_freeweight | 프리웨이트 여부 | **GENERATED** = type ∈ {barbell,dumbbell,bodyweight} (read-only) |
| pulley_ratio | 도르래비 | NN, 기본 1.0 (cable에서 의미) |
| bar_weight / bar_weight_unit | 바·레버 무게 | 값 있으면 unit ∈ {kg,lb} (CHECK 동기) |
| min_stack / max_stack / stack_weight / stack_unit | 스택 | 세 스택은 stack_unit 공유. stack_weight=JSONB |
| has_weight_assist | 어시스트 머신 | bool. true면 load_calc `body_weight − stack` |
| movement_label_en / movement_label_ko | 머신 정규 동작명 | machine/cable에 설정, `== exercises.name_en` |

**올바른 행 불변식**
- `equipment_type`은 5개 외 금지. `category`는 6개 부위 or NULL.
- 값 있는 무게엔 단위 필수(CHECK `chk_bar_unit_synced`/`chk_stack_unit_synced`).
- generic(barbell/dumbbell/bodyweight)은 **seed 결정적 uuid5 1행씩만** — 임의 v4 중복 금지.
- machine/cable은 `movement_label_en` 보유 + 동명 template exercise 존재.

**흔한 결함**
- 🔴 정본 generic 중복: `6eff9e86`(v4 덤벨, ad-hoc) vs `a0b9376d`(v5 seed) / `90ea9d0a`(Olympic) vs `f970fcc9` — dedup 대상(후속).
- 🔴 `32f43f66`(EZ Bar)·`c323aec6`(Assisted)가 default 허브로 오용 — equipments 자체는 정상, exercises가 잘못 가리킴.
- ❌ Smith machine `fe005947` type=`barbell`(→`machine` 교정 필요), orphan `f6fe186b`(name_en NULL).
- ⚪ name_en 결손 101 / 무사진 77 (기능영향 0).
- ❌ 중복명 60행(lat pulldown×5 등).

🔮 재설계 후: `movement_label_en` 제거 → 머신↔동작 **정션(eem repurpose)** 으로. generic 가짜행(bodyweight/barbell) 제거. equipments = 진짜 머신 + 숫자만.

---

## equipment_muscles — 기구↔근육 (기구당 N행)

**역할**: 머신 기구가 자극하는 근육. 루틴 생성 **머신 근육 필터의 진실원천**.

| 컬럼 | 의미 | 유효값/제약 |
|---|---|---|
| equipment_id | FK→equipments | NN |
| muscle_group_id | FK→muscle_groups | NN |
| involvement | 주/보조 | enum{`primary`,`secondary`} |
| activation_pct | 활성도% | 0–100 or NULL |

**올바른 행 불변식**
- 머신 1대당 **primary ≤ 2** (복합기구 화이트리스트 예외). 한 기구 5 primary = garbage.
- category=arms 머신 등 모든 기구에 적어도 관련 primary 1행 (결손 금지).
- muscle_group_id orphan 금지.

**흔한 결함**
- 🔴 garbage: Cable(`bf3d0dde`/`e94bec5c`, label=Machine Lat Pulldown)에 pec/삼각근/복근/**triceps 5 primary** → **"팔 루틴에 랫풀다운" 버그 직접 원인**. PR #284가 lat primary로 교정(배포 대기).
- ❌ 결손: 전체 ~130 중 27행(21%)만 채움, arms 16/17 미매핑. PR #287 ③ + 잔여 백필(movement_label JOIN).
- 제약: 백필은 `movement_label_en→name_en` JOIN만 (eem 집계 금지), muscle_group_id 하드코딩 금지(prod uuid5 아님).

🔮 재설계 후: 정션 기반으로 운동↔근육에서 파생되게 단순화 가능(검토).

---

## gyms — 헬스장 (≈5행)

| 컬럼 | 의미 | 유효값/제약 |
|---|---|---|
| id | PK | uuid |
| name | 헬스장명 | NN |
| address | 주소 | NN |
| latitude / longitude | 좌표 | NN |
| kakao_place_id | 카카오 장소 ID | UQ, nullable |

**올바른 행 불변식**: 실재 헬스장 = 유효 kakao_place_id + 기구 보유.

**흔한 결함**
- ❌ 테스트 gym: `스포애니 강남점`(kakao=12345678 가짜, 기구 0), `테스트 헬스장`×2 → DELETE 게이트(후속).
- 정상: 더찬스짐(`gym_id=ecdd073b…`, 기구 42).

---

## gym_equipments — 헬스장↔기구 (N:M)

**역할**: 각 헬스장이 보유한 **머신**. 루틴 생성 머신 후보의 gym 필터.

| 컬럼 | 의미 | 유효값/제약 |
|---|---|---|
| gym_id | FK→gyms | NN |
| equipment_id | FK→equipments | NN |
| (is_primary 등) | — | — |

**올바른 행 불변식**
- 등록 기구는 보통 머신(is_freeweight=false). 프리웨이트는 "전 헬스장 공통"이라 등록 안 함(현 정책 = 정상).
- orphan FK 금지.

**흔한 결함**: equip_count=0 gym(테스트) → 루틴 무기구 엣지케이스.

🔮 재설계 후: 정책 불변(머신만 gym 필터, 프리웨이트/맨몸/풀업바/딥스대 = 공통 baseline).

---

## (참고) user_gyms / exercise_equipment_map

- **user_gyms**: 유저↔헬스장(is_primary). 테스트 유저 정리 시 동반 점검.
- **exercise_equipment_map(eem, ≈26,102행)**: 런타임 **미사용**(default_equipment_id로 대체). PR-5 DROP 예정 → 검수 불요. 🔮 재설계서 머신↔동작 정션으로 **repurpose** 검토.

---

## 검수 순서 제안 (덤프 받은 뒤)
1. `muscle_groups.csv` — 26행, 슬러그 표준인지 (드리프트 잔존?)
2. `exercises.csv` — `default_equipment_id`별 group by → EZ Bar/Assisted 허브 카운트 확인
3. `exercise_muscles.csv` — exercise_id별 primary 0건 운동 추출
4. `equipment_muscles.csv` — equipment_id별 primary>2 추출(garbage), arms 결손 추출
5. `equipments.csv` — generic 중복(name_en 같은데 id 다름), type 오류(Smith)
6. `gyms.csv` / `gym_equipments.csv` — 테스트 gym, equip_count=0

> 게이트 SQL/카운트는 `2026-06-06-db-cleanup-inventory.md §9`와 1:1 대응.
