# 최종 보고서 — 운동-기구 재설계(WorkoutX) 영향 감사 + 클린슬레이트 마이그레이션

> 작성 2026-06-06 · ultracode 워크플로(18 에이전트) + codex 3-pass 리뷰 통합
> 요청: codex 리뷰 적극 활용 + 코드 정합성 분리지점 전수 + 논문제외 클린슬레이트 마이그 정리 + 자율 진행 후 보고

---

## 1. 무엇을 했나 (Executive Summary)

| 작업 | 방법 | 결과 |
|---|---|---|
| 코드 정합성 분리지점 전수감사 | 워크플로 8 서브시스템 fan-out → 적대 검증 (18 에이전트, 1.5M토큰) | **142건** (critical 84 / high 45 / medium 13) |
| 논문제외 클린슬레이트 마이그 | 설계 → 적대 안전검증 | **draft 작성, verdict SAFE** (papers 불가침 확인) |
| codex #1 설계 리뷰 | `codex exec` (ChatGPT auth) | 9개 설계 결함 |
| codex #2 마이그 리뷰 | `codex exec` | 2개 실문제 → **즉시 수정 반영** |
| codex #3 누락 교차검증 | `codex exec` | **+9건 누락**(프론트/문서/시드) + 분류오류 2 |

**총 분리지점 = 142 + codex#3 9 ≈ 151건.** 프론트엔드/문서/CI 레이어는 워크플로가 과소평가했고 codex #3가 보강.

**핵심 판정**: 마이그레이션의 논문 불가침·FK 안전순서·멱등은 3중 검증(워크플로 안전검증 + codex #2)으로 **SAFE**. 단 **구현 전 잠가야 할 사용자 결정 4건**(§5)이 있고, 이걸 정하기 전 코드 구현 착수 시 재마이그 거의 확실.

---

## 2. 산출물 (파일)

| 파일 | 내용 |
|---|---|
| `docs/spec/2026-06-06-exercise-equipment-workoutx-redesign.md` | 설계 스펙(D1~D12) |
| `docs/handoff/2026-06-06-code-coupling-report.md` | 142 분리지점 파일별 상세 |
| `docs/handoff/migrations-draft/20260606_clean_slate_reseed.py` | 클린슬레이트 마이그 draft (codex #2 수정 반영) |
| `docs/handoff/workoutx-raw/muscle_normalization.md` | 근육 정규화 맵(20종) |
| `docs/handoff/workoutx-raw/exercises.json` | WorkoutX 원본 캐시(1324, frozen) |
| `docs/handoff/codex-review-{1,2,3}-*.md` | codex 3패스 원문 |
| `docs/handoff/db-export/*.csv` | 현 prod 백업(.gitignore됨) |

---

## 3. 코드 정합성 분리지점 (레이어별)

| 레이어 | 건수 | 대표 파일 |
|---|---|---|
| **API** | 75 | `routines.py`(50), `gyms.py`(15), `admin.py`(5), `sessions.py`, `exercises.py` |
| **모델(ORM)** | 32 | `exercise.py`(12), `gym.py`(14), `routine.py`, `workout.py`, `user.py`, `__init__.py` |
| **테스트** | 12 | `test_routine_equipment_rag.py`(8) 등 |
| **서비스** | 11 | `load_calc.py`(5), `rag.py`(4), `routine_targets.py`, `po.py` |
| **MLOps/시드** | 6→**8** | `seed_exercises_workoutx.py`(+codex#3 2건), `seed.py` |
| **스키마(Pydantic)** | 4 | `equipment.py` 등 |
| **프론트엔드** ⚠️ | **+2 (codex#3)** | `WR01RoutineCreate.tsx`+`routines.ts`, `WH02Analysis.tsx` |
| **문서/CI** ⚠️ | **+5 (codex#3)** | `database-schema.md`, `erd-v2.3.md`, `templates/*`, `api-exercise-swap.md`, `test.yml` |

상세는 `2026-06-06-code-coupling-report.md`. **핵심 의존 제거 요소별 영향:**
- `default_equipment_id` 제거 → routines.py(필터/해석), gyms.py, 모델
- `equipment_muscles` 폐기 → gyms.py JOIN, routines.py 머신필터, 모델/`__init__`
- `movement_label_en/ko` 제거 → routines.py(WHERE/ORDER BY/라벨), gyms.py
- `is_freeweight` 제거 → routines.py(3곳 필터), admin.py, gyms.py
- `exercise_equipment_map` DROP → seed.py write, admin.py, 모델 관계
- `routine_exercises.equipment_id` NULL화 → 저장경로(운동 버림), 종목교체, sessions/PO 중량계산
- muscle taxonomy/category 변경 → 프론트 부위UI·분석화면, seed 스크립트, 문서

---

## 4. 클린슬레이트 마이그레이션 (논문 불가침)

**`docs/handoff/migrations-draft/20260606_clean_slate_reseed.py`** — 3 PHASE 구조:
- PHASE1 데이터 wipe (FK 자식-우선): programs/program_routines → 루틴계열 → log_sets/1rm → exercise_muscles → gym_equipments/reports/suggestions
- PHASE2 스키마 변경 (멱등): +load_mode, +exercise_equipment, −default_equipment_id, DROP eem/equipment_muscles, −movement_label/is_freeweight, equipment_id NULL화
- PHASE3 부모 wipe: equipments → exercises → muscle_groups

**보존(불가침)**: `papers`, `paper_chunks` (+ users/chat/notifications/equipment_brands/gyms/user_gyms)

**안전검증 (3중)**:
- ✅ papers/paper_chunks DELETE/DROP/ALTER **0건** — papers 참조 FK 2개(paper_chunks·routine_papers) 모두 child→parent 방향이라 자식 삭제가 papers 무손상. papers 미접촉이라 CASCADE 트리거 불가.
- ✅ FK 안전순서 — 5개 RESTRICT 전부 자식 선삭제 충족
- ✅ 멱등 — IF EXISTS / IF NOT EXISTS 가드

**codex #2 발견 → 수정 완료**:
- 🟠 program_routines 과삭제 → programs/program_routines를 **명시 wipe로 이동**(루틴 종속)
- 🟡 non-empty 부분파괴 → **D15 '전체 wipe'(workout_logs 헤더까지) 로 해소**, 건수 WARNING 로깅

⚠️ **DRAFT — 자동 실행 금지.** alembic 체인 투입 전: 백업 + 모델/코드 동반 변경(§3) + 재시드 마이그보다 선행 배치 필수.

---

## 5. ✅ 사용자 결정 확정 (4건, 2026-06-06)

> 모두 스펙 D13~D16 + 마이그/문서에 반영 완료.

1. **wipe 범위 = 전체 wipe (D15)** — 루틴+프로그램+`workout_logs`/`log_sets`/`user_exercise_1rm`+레퍼런스 전량. users/chat/profile/논문 보존. ("루틴만"은 FK상 불가했음) → 마이그 반영, non-empty도 진행+WARNING.
2. **머신 선택 = (b) (D14)** — LLM이 운동 선택 → `exercise_equipment ⋈ gym_equipments`로 M' 도출, M'≥2면 LLM 택1. **is_default 불필요.** → 스펙 §5 반영.
3. **`load_mode`에 `weighted` 독립 (D13)** — 11종. → 스펙 §3/§4/§6 + seed 재작성 노트 반영.
4. **SOT 정리 = 문서 업데이트 (D16)** — `database-schema.md`/`erd-v2.3.md`/`api-exercise-swap.md`/`templates/README.md`/`reconciliation`에 **superseded 배너** 부착 완료(전면 재작성은 구현 단계).

**기타 codex 지적(자율 반영 예정, 이견 시 알려주세요)**: Hip Flexors activation 1:1 유지(drop 모순 제거), name_ko UNIQUE 충돌 해소규칙, secondary 매핑 provenance, frozen exercises.json 사용, CI에 app/ tsc 추가.

---

## 6. 권장 구현 순서

1. **§5 결정 4건 확정** + SOT 정리(문서 superseded)
2. **seed 스크립트 재작성** (codex#3 critical): category=bodyPart, equipment→load_mode 10종 보존, eem write 제거
3. **모델/스키마 변경** (load_mode, exercise_equipment, 제거 컬럼/테이블/관계) — §3 ORM 32건
4. **마이그레이션** (스키마+클린슬레이트) → 백업 후 적용
5. **API/서비스 리팩터** — routines(단일경로)/gyms/sessions/load_calc/rag/po (§3 API 75 + 서비스 11)
6. **재시드** — muscle_groups(20)+한글 → 실물기구 → WorkoutX exercises+muscles+activation병합 → 머신 N:M(Gemini+검증)
7. **프론트엔드** — 부위 UI 10분류, 분석화면 집계키 (codex#3 high)
8. **테스트/CI** — load_calc/rag 갱신 + app tsc job

---

## 7. 잔존 리스크
- 프론트 영향은 codex#3가 표본 확인했으나 app/src 전수는 아님 — 구현 시 grep 재확인 권장
- 머신 N:M(Gemini) 품질은 실물 기구 데이터 완전성에 의존 (§"유저 우선 입력 = equipments/gym_equipments")
- activation% 병합(해부학26→WorkoutX19 MAX)은 해상도 손실 — 수용 결정됨
- 재시드 WorkoutX 라이브 의존 제거 위해 frozen `exercises.json`(1324) 고정 사용 권장
