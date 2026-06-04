# 최종 설계 스펙 — 기구-중심 루틴 재설계 (Equipment-Centric Redesign)

> 작성: 2026-06-04 / 브랜치: `feat/jingyu/muscle-equipment-redesign`
> 배경 버그: 헬스장(찬스짐)을 골라도 그 헬스장 기구가 아니라 운동명(벤치프레스) 기준으로 루틴이 짜임.
> 사용자 핵심 원칙: **기구(equipment)가 1차 단위**여야 하고, 추상 "운동"을 기구에 매핑한 현재 구조(`exercise_equipment_map`)가 버그의 뿌리.
> 도출 방법: `equipment-centric-redesign-design` 워크플로우(4안 생성→심사→합성). 점수 clean=26 / minimal=24 / literal=24 / hybrid=21.

## 0. 설계 보정 — 프리웨이트 공통 규칙 (2026-06-04, 사용자 확정)

**규칙: 프리웨이트(barbell/dumbbell/bodyweight)는 모든 헬스장이 공통 보유로 간주한다. 머신/케이블(cable/machine)만 헬스장별로 다르다.** 이 보정이 아래 §3·§5의 일부를 다음과 같이 덮어쓴다(override):

- **프리웨이트 = 종목(운동) 단위, 전 헬스장 공통.** 근육→프리웨이트 목록은 `exercise_muscles`(이미 시드됨)에서 해당 근육을 primary로 하는 free-weight 운동을 뽑는다. gym_equipments로 필터하지 않는다. 각 운동의 구현 기구(바벨/덤벨)는 `exercise_equipment_map`의 free-weight 행에서 얻는다(이 용도로만 유지).
- **머신 = 기구 단위, 헬스장별.** 근육→머신 목록은 `equipment_muscles`(신규 백필) + `gym_equipments(gym_id)` 조인. `is_freeweight=false`.
- **gym_equipments에는 머신/케이블만 등록**(프리웨이트는 등록 안 함, 공통으로 가정).
- **§5 M2 백필은 "머신만"** 대상으로 축소(`is_freeweight=false`). 프리웨이트의 근육 연결은 기존 `exercise_muscles` 재사용.
- **루틴 후보 = 그 헬스장 머신 + 전 헬스장 공통 프리웨이트.**
- routine_exercises 한 행 = (equipment_id NOT NULL, exercise_id NOT NULL). 머신: equipment_id=머신, exercise_id=머신 movement_template. 프리웨이트: exercise_id=종목, equipment_id=공통 바벨/덤벨.
- `GET /gyms/{id}/equipments?muscle_group_id=`: 응답을 `free_weights[]`(exercise_muscles 출처, 공통) + `machines[]`(equipment_muscles+gym_equipments 출처, 헬스장별)로 분리.

## 1. 한줄 요약 + 채택 근거

**한줄 요약**: `equipments`를 루틴의 1차 단위로 격상한다 — LLM과 루틴 항목이 추상 "운동명"이 아니라 그 헬스장에 실재하는 기구 row(`equipment_id`)를 직접 다루게 만들고, `exercise_id`는 1RM/근육활성도/논문 추적을 위한 **보조 라벨로 강등(단, NOT NULL 유지)**한다.

기반은 최고점 **[클린 기구-중심 재구축]**:
- LLM에 `available_exercises:list[str]` 대신 `available_equipments:list[{equipment_id,label,type}]`를 넘겨, `_resolve_exercise_id`의 5단계 fuzzy 매칭과 `_fetch_exercise_equipment`의 `.limit(1)` 임의선택을 **동시에 구조적으로 제거**한다.
- `exercises`를 물리 rename 하지 않고 의미만 movement_template로 재정의해 5개 FK를 무손실 보존.
- `exercise_equipment_map` DROP을 별도 승인 게이트로 분리하는 점진 마이그레이션.

접목한 아이디어:
- **[최소변경]**: LLM은 UUID가 아니라 `equipment_label` + 보조 `equipment_type` 출력 → 서버가 label→id 매핑(실패 시 fuzzy fallback). core lift 4종 `name_en` 동결. 신규 엔드포인트가 독립 가치.
- **[사용자 명시 구조]**: `equipment_type` 보존이 load_calc/po/sessions 0줄 변경의 핵심. `routines.py:930` fallback을 "빈 결과 + 명시 안내"로 교체.
- **[하이브리드]**: **`workout_log_sets.exercise_id`가 NOT NULL RESTRICT(workout.py:53)** → routine_exercises.exercise_id를 nullable로 강등하면 머신 세션 기록이 깨짐. 따라서 exercise_id를 **NOT NULL 유지**, equipment_id를 NOT NULL로 승격하는 "둘 다 NOT NULL" 모델 채택.

## 2. 최종 데이터 모델

신규 테이블 0개, DROP 0개(정리 단계는 별도 승인). 기구가 1차 단위.

### 2-1. `equipments` (컬럼 추가)
- `movement_label_ko` varchar(150) NULL — 루틴 카드 표시 동작명("체스트 프레스")
- `movement_label_en` varchar(150) NULL — RAG/영문 라벨("Chest Press")
- `is_freeweight` boolean GENERATED ALWAYS AS (`equipment_type IN ('barbell','dumbbell','bodyweight')`) STORED — 프리/머신 분기 단일 진실원천
  - ORM: `mapped_column(Boolean, Computed("equipment_type IN ('barbell','dumbbell','bodyweight')", persisted=True))`
- `equipment_type` enum **절대 불변** (load_calc/po/sessions 의존). 나머지 기존 컬럼 유지.

### 2-2. `equipment_muscles` (빈 테이블 → 채움)
- `activation_pct` int NULL **신설** (exercise_muscles와 동형). "근육→프리/머신 목록" 조회의 조인 축.

### 2-3. `routine_exercises` (제약 승격)
- `equipment_id`: nullable/SET NULL → **NOT NULL/RESTRICT** (1차 단위 승격)
- `exercise_id`: **NOT NULL/RESTRICT 유지** (보조 라벨, 1RM·근육·논문 조인 키)
- `display_name` varchar(200) NULL **신설** — 저장 시점 동작명 스냅샷

### 2-4. `exercises` → 의미 재정의 = movement_template (물리 rename 없음)
테이블명·PK·5개 FK 보존. 의미만 "정규화된 동작 식별자(1RM/core lift/논문/근육활성도 안정 키)"로 격하. 1차 조회 경로에서 빠짐.

### 2-5. `exercise_equipment_map` (버그의 뿌리) → DEPRECATE
스키마 유지, 읽기/쓰기 경로에서 제거. M2 백필 소스로 1회 사용 후, 별도 승인 게이트(M6)에서만 DROP.

### 2-6. 텍스트 ER
```
                          muscle_groups (21 seed, 불변)
                            ▲                    ▲
        equipment_muscles   │                    │  exercise_muscles
        (1급, 신규 시드,     │                    │  (이력/세션분석 보존)
         activation_pct)    │                    │
   gyms ──< gym_equipments >── ★ equipments ★ ──────< routine_exercises
                            (1차 단위)                  equipment_id NOT NULL (본체)
                            movement_label_ko/en        exercise_id   NOT NULL (보조 라벨)
                            equipment_type ─────┐       display_name  (스냅샷)
                            is_freeweight        │           │ exercise_id (보조)
                                                 ▼           ▼
                                  load_calc/po/sessions   movement_templates (구 exercises)
                                  (equipment_type, 무변경)  └─ user_exercise_1rm
                                                            └─ workout_log_sets (exercise_id NOT NULL)
                                                            └─ core_lifts (name_en) / routine_papers

   [DEPRECATED, M6에서 DROP] exercise_equipment_map
```

## 3. 핵심 흐름

### 3-A. "근육 → 프리/머신 목록 → 루틴 추가"
신규 엔드포인트 `GET /api/v1/gyms/{gym_id}/equipments?muscle_group_id={uuid}&involvement=primary`:
```sql
SELECT e.id AS equipment_id, COALESCE(e.movement_label_ko, e.name) AS label,
       e.equipment_type, e.is_freeweight, e.image_url, b.name AS brand
FROM equipment_muscles em
JOIN equipments e      ON e.id = em.equipment_id
JOIN gym_equipments ge ON ge.equipment_id = e.id AND ge.gym_id = :gym_id
LEFT JOIN equipment_brands b ON b.id = e.brand_id
WHERE em.muscle_group_id = :muscle_group_id AND em.involvement = 'primary'
ORDER BY e.is_freeweight DESC, label;
```
응답을 `is_freeweight`로 `free_weights[]`/`machines[]` 분할. 운동(exercise) 미경유 → 사용자 원칙 충족.
루틴 추가: 고른 `equipment_id`를 그대로 저장, `exercise_id`는 기구의 movement_label_en→movement_template 매칭(M1 보장), `display_name=label` 스냅샷.

### 3-B. "헬스장 기구로만 루틴 생성" (`POST /routines/generate`)
1. gym_id 필수, 후보 기구 조회(운동명 아님): `equipments JOIN gym_equipments(gym_id) [LEFT JOIN equipment_muscles(target_muscles, primary)]`.
2. 프롬프트(`rag.py:_build_routine_prompt`): `available_exercises` → `available_equipments`(label+type+`[MACHINE]`/`[FREE]` 태그), "use ONLY these exact labels".
3. LLM 출력: `equipment_label` + 보조 `equipment_type`. 서버가 gym 후보 집합 내 exact match → 실패 시 기존 fuzzy를 fallback으로만.
4. **fallback 무음실패 제거**: gym_id 있는데 후보 0개면 전체 DB로 새지 않고 `404 NOT_FOUND` (`code: NOT_FOUND`, `details.reason: no_gym_equipments`). gym_id 자체가 없을 때만 전체 DB 허용.
5. 저장: equipment_id 그대로 → routine_exercises.equipment_id(NOT NULL). `.limit(1)` 임의선택 삭제.

### 3-C. routine_exercises 저장 내용
equipment_id(NOT NULL, 정체성/계산) + exercise_id(NOT NULL, 1RM/근육/세션/논문 조인) + display_name(스냅샷).

## 4. 기존 기능 보존
| 기능 | 보존 방법 | 변경 |
|---|---|---|
| load_calc (equipment_type match) | enum 컬럼 불변, equipment_id NOT NULL이라 항상 직접 획득 | 0줄 |
| po.py (INCREASE dict) | 동일 enum 보존 | 0줄 |
| sessions.py PO (225,528) | equipment_id NOT NULL 승격 → else "machine" fallback 미발동, 정확도↑ | 0줄(시그니처) |
| 1RM (user_exercise_1rm) | exercise_id NOT NULL 유지 → movement_template 단위 무손상 | 0줄 |
| core lift (name_en) | bench/squat/deadlift/OHP 4종 name_en 동결 | 신설 시 주의 |
| 근육활성도 (exercise_muscles.activation_pct) | 삭제 안 함, equipment_muscles.activation_pct는 보조 | 둘 다 유지 |
| RAG 생성 | available_equipments 전환, SSE/격리/threshold 불변 | 프롬프트+파서 |
| workout_log_sets (exercise_id NOT NULL) | routine_exercise.exercise_id NOT NULL이라 항상 유효 | 0줄 |

핵심: **equipment_type 보존 + exercise_id NOT NULL 유지**가 보존 전략의 전부.

## 5. Alembic 마이그레이션 플랜 (무손실·롤백·비파괴)
- **M1** equipments 컬럼 추가(movement_label_*, is_freeweight generated) + 머신 movement_template 신설(Chest Press, Lat Pulldown(machine), Leg Press, Pec Deck 등; core lift 4종 미변경) + 해당 exercise_muscles 시드.
- **M2** equipment_muscles.activation_pct 추가 + 결정론적 백필(`DISTINCT ON (equipment_id, muscle_group_id)` + `ORDER BY` primary 우선/activation_pct DESC). 범용 프리웨이트(primary 근육 ≥4) 검증·강등.
- **M3** movement_label 백필(exercise_equipment_map의 name/name_en → 매핑 기구, DISTINCT ON 1개 결정).
- **M4** routine_exercises.display_name 추가 + equipment_id NULL 행 백필(routine gym_id+exercise_id 결정론 선택). NULL 잔존 1개라도 있으면 승격 보류.
- **M5** equipment_id NOT NULL/RESTRICT 승격(사전 NULL=0 가드, `lock_timeout`, FK `NOT VALID`→`VALIDATE` 2단계).
- **M6 (별도 PR, 사용자 명시 승인 필수, 파괴적)** exercise_equipment_map DROP(백업+회귀 통과 후).
- 코드 PR: `routines.py:930` fallback → 404.

## 6. 블라스트 반경 & 테스트
수정: routines.py(후보빌더/`_fetch_exercise_equipment`/`_resolve_exercise_id`/저장/PATCH), rag.py(프롬프트/파서/fixture), gyms.py(신규 엔드포인트), models/gym.py, models/routine.py, admin.py, schemas. **무변경(보존): load_calc.py, po.py, sessions.py 시그니처, core_lifts.py, user.py, workout.py.**
프론트: 근육→기구 화면(free/machine 탭), 루틴 카드 display_name, 404 분기.
테스트: load_calc/po/rag(search_chunks) 100% 커버 유지(회귀 가드) + 신규(엔드포인트, gym-only 생성, 404, label→id 매핑, 마이그레이션 결정론/라운드트립, 머신 세션 기록).

## 7. 단계적 실행 순서 (PR 분할, 위험 낮은 순)
1. **PR-1 (위험 최저)**: M1 일부(컬럼) + M2(equipment_muscles 백필) + 신규 `GET /gyms/{id}/equipments` + 프론트 근육→기구 화면. 루틴 생성 무변경, 읽기 전용 신규 기능.
2. **PR-2**: M1 나머지(머신 movement_template + exercise_muscles 시드) + M3.
3. **PR-3 (핵심)**: rag.py available_equipments 전환 + routines.py 재작성 + `:930` fallback→404. equipment_id는 아직 nullable.
4. **PR-4**: M4 + M5(NOT NULL/RESTRICT 승격).
5. **PR-5 (승인 게이트)**: M6 — exercise_equipment_map DROP.

## 버그가 사라지는 메커니즘
재설계 후 LLM에 넘기는 단위가 기구 row다. 찬스짐 후보는 gym_equipments JOIN 결과 "Chest Press Newtech" 기구이고 라벨은 "체스트 프레스". **Barbell Bench Press라는 추상체가 찬스짐 gym_equipments에 없으므로 후보에 오를 수 없다.** 1동작→N기구 매핑이 조회 경로에서 제거되어 `.limit(1)` 임의선택도 운동명↔기구 불일치도 발생 불가. equipment_id NOT NULL 승격으로 "운동만 있고 기구 모호" 상태가 DB에서 금지.
