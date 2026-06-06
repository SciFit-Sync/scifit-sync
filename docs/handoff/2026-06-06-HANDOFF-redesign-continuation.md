# 🧭 마스터 핸드오프 + 실행 플랜 — 운동-기구 재설계(WorkoutX)

> 작성 2026-06-06 · **다른 세션이 이 문서 하나로 이어받아 실행** 가능하도록 작성.
> 단일 정본(SOT) = [`docs/spec/2026-06-06-exercise-equipment-workoutx-redesign.md`](../spec/2026-06-06-exercise-equipment-workoutx-redesign.md).
> 상태: **설계·영향감사·기구데이터 준비 완료 / 구현 미착수.** branch `fix/jingyu/default-equipment-remap`, commit `409d29e`.

---

## 0. 목표 (한 줄)
운동/기구를 **운동-중심 + 기구↔운동 N:M + 프리웨이트 baseline + WorkoutX 분류**로 재설계하고, 논문 제외 **클린슬레이트 재시드**로 더티 데이터(95% 무근육·553 default 오배정·garbage primary)를 일소.

## 1. 왜 (시작점)
"팔 루틴에 랫풀다운/전신이 나옴" 버그 → 근본원인 = (a) exercise_muscles 95% 비어 근육필터 무력, (b) equipment_muscles garbage primary, (c) default_equipment_id 553 오배정, (d) 머신 1:N을 movement_label 단수로 못 담는 구조 결함. → 패치 대신 재설계.

## 2. 확정 결정 (D1~D16) — 변경 금지
| # | 결정 |
|---|---|
| D1 | taxonomy = **WorkoutX** (bodyPart 10 / target 19+Hip Flexors=20 / equipment class) |
| D2 | **(B)** generic implement 행 제거. 프리웨이트는 equipment 행 없음, `exercises.load_mode`+load_calc 상수 |
| D3 | 기구↔운동 **N:M 신규 `exercise_equipment`** (eem 폐기 후) |
| D4 | 프리웨이트/맨몸/풀업바/딥스대 = **baseline**(항상 가용), 머신만 gym 필터 |
| D5 | `equipment_muscles` 폐기 → 운동에서 파생 |
| D6 | `movement_label_en/ko`·`default_equipment_id`·`equipments.is_freeweight` 제거 |
| D7 | `routine_exercises.equipment_id` **NULL 허용**(프리웨이트=NULL) |
| D8 | EZ Barbell / Trap Bar = 별도 load_mode (bar 무게 다름) |
| D9 | activation% = 해부학 시드(3893행) → 병합 맵(MAX, primary 우선) salvage |
| D10 | 한글명(운동·근육) = Gemini 일괄 → 파일 → 사용자 검증 |
| D11 | 클린슬레이트 재시드(논문 제외) |
| D12 | 머신↔실물기구 = Gemini 판단 → 파일 → 사용자 검증 (실물 기구 적재 후) |
| **D13** | `load_mode`에 **`weighted` 독립** (체중+외부부하). 총 11종: barbell·ez_barbell·trap_bar·dumbbell·bodyweight·weighted·kettlebell·band·cable·machine·cardio |
| **D14** | 머신 선택 **(b)**: LLM이 운동 선택 → `exercise_equipment ⋈ gym_equipments`로 M' 도출. M'=0(머신)제외/M'=1자동/**M'≥2 LLM택1**. is_default 불필요 |
| **D15** | **전체 wipe**: 루틴+프로그램+`workout_logs`/`log_sets`/`user_exercise_1rm`+레퍼런스. **users/chat/profile/논문 보존** |
| **D16** | SOT = 관련 문서 업데이트(superseded 배너 부착 완료) |

## 3. 🔴 절대 가드레일 (틀리면 안 되는 것)
1. **`papers`/`paper_chunks`/ChromaDB 절대 불가침** — DELETE/DROP/ALTER 0건. (RAG가 paper_chunks 전제)
2. **FK 안전 삭제순서** — 자식부터: routine_papers→routine_exercises→routine_days→workout_routines, log_sets→logs, exercise_muscles, (eem/equipment_muscles DROP), gym_equipments → **그 다음** equipments→exercises→muscle_groups. (RESTRICT: routine_exercises·workout_log_sets→exercises/equipments, exercise_muscles·equipment_muscles→muscle_groups)
3. **마이그는 모델/코드 변경과 함께** 배포 — 마이그만 적용+구버전 앱 = import/쿼리 크래시.
4. **백업 필수** — 적용 직전 `db-export` 스냅샷.
5. **Alembic 단독** — Supabase 대시보드 직접 수정 금지. revision id ≤32자.
6. **prod = Supabase hnwegx** (server/.env DATABASE_URL은 빈 dev). 읽기=ANON PostgREST.

## 4. 현재까지 완료된 것
- ✅ 설계 스펙 (D1~D16): `docs/spec/2026-06-06-exercise-equipment-workoutx-redesign.md`
- ✅ 코드 정합성 분리지점 **151건**(워크플로142 + codex#3 9): `docs/handoff/2026-06-06-code-coupling-report.md` (레이어: API 75 / ORM 32 / 테스트 12 / 서비스 11 / 시드 8 / 스키마 4 / 프론트 2 / 문서·CI 5)
- ✅ 클린슬레이트 마이그 draft(전체 wipe, 안전검증 SAFE): `docs/handoff/migrations-draft/20260606_clean_slate_reseed.py`
- ✅ codex 3-pass: `docs/handoff/codex-review-{1,2,3}-*.md`
- ✅ WorkoutX 원본 캐시(1324): `docs/handoff/workoutx-raw/exercises.json`
- ✅ 근육 정규화 맵(20종): `docs/handoff/workoutx-raw/muscle_normalization.md`
- ✅ 프리웨이트 load_mode reference: `docs/handoff/workoutx-raw/freeweight_load_modes.csv`
- ✅ **실물 기구 데이터 정리 완료** (아래 §5)
- ✅ 관련 문서 superseded 배너: database-schema.md/erd-v2.3.md/api-exercise-swap.md/templates/README.md/reconciliation

## 5. 기구 데이터 준비 상태 (유저 수동 입력분)
> 위치: `docs/handoff/db-export/` (.gitignore — 유저 이메일 포함). 시드 단계에서 소스로 사용.

| 파일 | 상태 |
|---|---|
| `equipments.csv` | **132 머신** (machine 130 + cable 2). 비머신 0, 브랜드없음 0. generic 프리웨이트·Assisted placeholder·Smith 중복 제거 완료 |
| `equipment_brands.csv` | 14개. NEM→Newtech dedup 완료. 미사용 7개(Technogym 등) **유지 결정**. dangling 0 |
| `gym_equipments.csv` | 32건. orphan 0 |
| `freeweight_load_modes.csv` | barbell20·ez10·**trap25(확정)**·dumbbell증분·weighted=bw+added 등 |

**⏳ 미완 (유저 차례)**: `equipments.csv`의 **한글 `name`** 채우기 (현재 비어있음, name_en만 채워짐). 받으면 그대로 반영.

## 6. 실행 플랜 (Phase별, 순서 준수)

> 각 Phase 끝에 **검증 게이트** 통과 후 다음으로. 코드 변경은 §4 code-coupling-report의 file별 목록을 체크리스트로.

### Phase 0 — 선결 입력
- [ ] 유저: `equipments.csv` 한글 name 채움
- [ ] WorkoutX API 키 유효 확인 (probe: `docs/handoff/workoutx-raw/probe_workoutx.py`)

### Phase 1 — 시드 스크립트 재작성 (codex#3 critical 우선)
- [ ] `mlops/scripts/seed_exercises_workoutx.py` 재작성:
  - `category` = WorkoutX **bodyPart 원문** (target→6부위 축약 **금지**)
  - `equipment` → **load_mode 11종 보존** (ez/trap→barbell 붕괴 금지, kettlebell/band/cardio 포함). 미지원값 skip 아닌 **fail-fast**
  - **secondaryMuscles 수집** 추가, eem write **제거**
  - 소스 = frozen `exercises.json`(1324) 권장(라이브 재호출 변동 차단)
- [ ] 기구 시드: `equipments.csv`(132)+`equipment_brands.csv`+`gym_equipments.csv` 적재 스크립트/마이그
- [ ] 근육 시드: `muscle_groups` 20종(+name_ko) — `muscle_normalization.md`
- [ ] `exercise_muscles` 시드: target→primary, secondaryMuscles→정규화맵(drop 5종), activation%=병합맵
- 게이트: primary 결손 0(cardio 제외), load_mode NULL 0, muscle orphan 0

### Phase 2 — 모델/스키마 (ORM 32건, code-coupling-report 참조)
- [ ] `exercise.py`: +`load_mode`, −`default_equipment_id`, −`ExerciseEquipmentMap`/`equipment_maps`, +`ExerciseEquipment` 모델
- [ ] `gym.py`: −`movement_label_en/ko`, −`is_freeweight`, −`EquipmentMuscle`, `EquipmentBodyCategory`→WorkoutX bodyPart(또는 varchar)
- [ ] `routine.py`: `equipment_id` nullable
- [ ] `models/__init__.py`: 폐기 모델 export 제거
- 게이트: `python -c "import app.models"` 성공, ruff 통과

### Phase 3 — 마이그레이션
- [ ] `20260606_clean_slate_reseed.py` draft → `server/alembic/versions/` 이동 (down_revision=현 head)
- [ ] 백업(db-export 스냅샷) 후 로컬 DB 적용 → 검증 → prod
- [ ] 재시드 마이그/스크립트(Phase1)는 clean_slate **뒤에** 체인
- 게이트: papers/paper_chunks 행수 불변, 재시드 후 게이트 SQL 0건

### Phase 4 — API/서비스 (86건)
- [ ] `routines.py`: `_build_rag_profile` 단일경로(machine/free_stmt 통합), `_resolve_label_to_ids` 운동해석, 머신선택(b)
- [ ] `rag.py`: `_build_routine_prompt` 운동 계약, [MACHINE]/[FREE] 제거
- [ ] `load_calc.py`: `exercise.load_mode` 분기 + 프리웨이트 상수(freeweight_load_modes.csv)
- [ ] `sessions.py`/`routine_targets.py`/`po.py`: equipment_id NULL 대응(프리웨이트 PO/중량)
- [ ] `gyms.py`: equipment_muscles JOIN 제거 → 정션 경유 파생
- 게이트: 루틴 생성 E2E(가슴/팔/맨몸), load_calc 100% 테스트 pass

### Phase 5 — 프론트 (codex#3)
- [ ] `WR01RoutineCreate.tsx`+`routines.ts`: 부위 10분류(WorkoutX bodyPart), 구 alias 제거, union type
- [ ] `WH02Analysis.tsx`: 집계키를 해부학 name_ko 하드코딩 → 영문 canonical/서버 메타로
- 게이트: `cd app && npx tsc --noEmit`

### Phase 6 — 테스트/CI
- [ ] load_calc/po/rag 테스트 갱신(load_mode 케이스)
- [ ] `.github/workflows/test.yml`에 app tsc/lint job 추가
- 게이트: 전체 CI green

### Phase 7 — Gemini 산출물 (검증 루프)
- [ ] 한글명(운동1401+근육20), 머신↔운동 N:M(`exercise_equipment`), secondary 정규화 → **파일 산출 → 유저 검증 → 적재**
- [ ] 머신 N:M은 **실물 기구 적재(Phase1) 후** 실행 (선결)

## 7. PR 처분
- ✅ 유지: **#281**(루틴 품질)
- ❌ 폐기(본 재설계가 대체): #287(해부학 normalize/activation), #284(arm fix), #283(default recover), 현 브랜치 default-remap
- ⚠️ salvage: `muscle_activation_seed.csv`(activation% 수치, 병합), `curated-72`
- 🔄 PR-5(eem DROP) → 본 재설계가 흡수

## 8. 파일 인덱스
| 파일 | 용도 |
|---|---|
| `docs/spec/2026-06-06-exercise-equipment-workoutx-redesign.md` | **SOT 설계** |
| `docs/handoff/2026-06-06-FINAL-REPORT-redesign.md` | 감사+마이그+codex 최종보고 |
| `docs/handoff/2026-06-06-code-coupling-report.md` | 151 분리지점 (구현 체크리스트) |
| `docs/handoff/migrations-draft/20260606_clean_slate_reseed.py` | 클린슬레이트 마이그 draft |
| `docs/handoff/workoutx-raw/exercises.json` | WorkoutX 원본 1324 (frozen 시드소스) |
| `docs/handoff/workoutx-raw/muscle_normalization.md` | secondary 40→20 정규화 맵 |
| `docs/handoff/workoutx-raw/freeweight_load_modes.csv` | 프리웨이트 load_mode 상수 |
| `docs/handoff/workoutx-raw/probe_workoutx.py` | WorkoutX 재수집 스크립트 |
| `docs/handoff/db-export/*.csv` | 기구 데이터(유저 입력) + prod 백업 (.gitignore) |
| `docs/handoff/codex-review-{1,2,3}-*.md` | codex 3-pass 원문 |
| 메모리 `project_workoutx_redesign_plan` | cross-session 요약 |

## 9. 다음 세션 시작 방법
1. 이 문서 + `docs/spec/2026-06-06-exercise-equipment-workoutx-redesign.md` 읽기
2. §3 가드레일 숙지 (papers 불가침, FK 순서)
3. 유저에게 `equipments.csv` 한글 name 받았는지 확인
4. §6 Phase 1부터 순서대로, 각 Phase 게이트 통과 확인
5. 막히면 `code-coupling-report.md`에서 해당 file 항목 참조
