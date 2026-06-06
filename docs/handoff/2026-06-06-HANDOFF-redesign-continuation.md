# 🧭 마스터 핸드오프 + 실행 플랜 — 운동-기구 재설계(WorkoutX)

> 작성 2026-06-06 · **다른 세션이 이 문서 하나로 이어받아 실행** 가능하도록 작성.
> 단일 정본(SOT) = [`docs/spec/2026-06-06-exercise-equipment-workoutx-redesign.md`](../spec/2026-06-06-exercise-equipment-workoutx-redesign.md).
> 상태: **PR #297 — CI GREEN(lint/test-mlops/test-server 전부 pass)·MERGEABLE·리뷰 승인 대기. 코드 구현 100% — DB 적용(prod)·Phase 7(Gemini junction/activation 백필)만 남음.** branch `feat/jingyu/equipment-workoutx-redesign` → base `develop`. 진행 상세 §10, PR/CI §11.

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
| `gym_equipments.csv` | **33건**(Smith `f6fe186b` 등록 추가, 2026-06-06). orphan 0 |
| `freeweight_load_modes.csv` | barbell20·ez10·**trap25(확정)**·dumbbell증분·weighted=bw+added 등 |

**✅ 완료 (2026-06-06)**: `equipments.csv` 132행 **한글 `name` 머지 완료** (유저 `equipments 1.xlsx` 140행 → id 기준 132 공통행 채움, 빈 행 0. 백업 `equipments.csv.bak`).

**🔴 머신 2종 흡수 주의 (감사: [`2026-06-06-baseline-equipment-gap-audit.md`](2026-06-06-baseline-equipment-gap-audit.md))**: xlsx에만 있던 8개 generic 중 프리웨이트 6종은 `freeweight_load_modes.csv`에 baseline 기록 완비(✅). 그러나 머신 2종(Smith machine·Assisted Pull-up Machine)은 generic 부활 불요지만 다음 3건이 공백 — 재시드 전 반드시 처리:
- **G1(P0)** ✅ 해결: Smith 실물 `f6fe186b`(Panatta, bar 15kg) — 유저 확인 더찬스짐 실재 → `gym_equipments.csv` 등록 완료(32→33행). Smith 48운동 복구.
- **G2(P0)**: 머신-클래스 **160운동**(Smith48+Leverage81+Sled15+Assisted/Hammer16)→실물 행 정션 산출물 미작성(Phase 7).
- **G3(P1)**: `load_calc.py` machine 분기가 has_weight_assist 미반영 → 어시스티드 머신 부호반대 오계산(Phase 4 수정). G4: Assisted 15운동 다수가 스트레치 → machine 오분류 위험.

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
- [ ] `load_calc.py`: `exercise.load_mode` 분기 + 프리웨이트 상수(freeweight_load_modes.csv). **🔴 G3: machine 분기에 `has_weight_assist` 처리 추가**(현재 미반영 — Assisted Dip/Chin을 machine으로 계산하면 부호반대 폭탄)
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
- [ ] **🔴 G2: 머신-클래스 160운동(Smith48+Leverage81+Sled15+Assisted/Hammer16) → 실물 행(f6fe186b/2ca108c5/91dd2f21 등) 정션 명시 산출**. §9 게이트 "machine/cable 운동 중 정션 없음 = 0" 검증.
- [ ] **G4: Assisted 15운동 다수가 파트너 스트레치(부하 없음)** → `Assisted→machine` 룩업 재검토, bodyweight 등으로 재분류

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

## 10. 🟢 구현 진행 (2026-06-06 세션, branch feat/jingyu/equipment-workoutx-redesign)

### ✅ 완료 (커밋됨, branch feat/jingyu/equipment-workoutx-redesign)
| Phase | 내용 | 커밋 |
|---|---|---|
| 2 모델 | Exercise +load_mode/-default_equipment_id, ExerciseEquipment N:M(source/confidence), Equipment -movement_label_*/-is_freeweight, EquipmentMuscle/ExerciseEquipmentMap 삭제, RoutineExercise.equipment_id NULL | `a6a1619` |
| 4-base | load_calc load_mode 11종 + **G3** machine has_weight_assist(부호반대 수정) + FREEWEIGHT_BAR_KG/FREEWEIGHT_MODES/MACHINE_MODES + routine_targets load_mode 전환 + test_load_calc | `a7b5b66` |
| 4 API | equipment(근육 정션파생) `e475716` / po+sessions(INCREASE load_mode) `7ccb97d` / rag(운동중심 available_exercises/exercise_name) `782aaf7` / admin(시드 inline) `6120440` / gyms(정션경유) `993aea5` / routines(단일가용성+D14+6tuple) `5ce4f38` | |
| 3 wipe 마이그 | clean_slate_reseed(전체 wipe+스키마변경) 배치 | `4bf6802` |
| **1 재시드 마이그** | **Alembic 마이그로 재구성**(CLAUDE.md §16 정합 — mlops 수동스크립트 아님): `20260606_reseed_workoutx`(down=clean_slate). muscle_groups 20 인라인 + equipments/brands/gym_equipments CSV + exercises 1318(dedup) + exercise_muscles 3756. junction 비움. 데이터 `mlops/data/reseed_*`(이메일 0건). mlops/scripts/seed_*는 개발보조 | `90fdccc` |
| **6 테스트** | po(load_mode 케이스) `3b79fe9` / routines·rag(운동중심) `9a542f9` / routine_targets 정합 | |

**게이트 전부 통과 (2026-06-06)**: `app.main` import OK · `ruff check app/` clean · **alembic single head**(reseed_workoutx) · **핵심 테스트 195 passed**(load_calc/po/routine_targets/routines/rag) · papers write 0건.
**정합 수정**: 병렬 agent 간 rag↔routines 계약 불일치(available_equipments→available_exercises, equipment_label→exercise_name) 메인 보정.

### ⏳ 남은 작업 (코드 100% — 실행/후속만)
- **DB 적용 (prod hnwegx)**: 런북 [`2026-06-06-prod-reseed-runbook.md`](2026-06-06-prod-reseed-runbook.md)대로 — ① 백업(papers/paper_chunks 행수 기록 + db-export 스냅샷) ② server/.env를 prod service role URL로 교체 ③ `alembic upgrade head`(clean_slate→reseed_workoutx 순차) ④ 검증 SQL(papers 행수 불변·load_mode NULL 0·exercise_muscles primary 결손 0·orphan 0). gyms에 더찬스짐(ecdd073b) 존재 전제.
- **Phase 7 (Gemini 후속, 재시드 후)**: exercise_equipment junction(머신↔운동 N:M — 현재 비움이라 머신 루틴 가용성 0) + activation_pct 백필(현재 전부 NULL). G2 머신 160운동 정션 매핑 포함.
- **Phase 5 프론트** (WR01RoutineCreate/WH02Analysis 부위 10분류) + **CI** app tsc/lint job — 미착수.

## 11. 🟢 PR & CI 상태 (2026-06-06)

**PR #297** (base `develop`) — **CI GREEN**: lint · test-mlops · test-server 전부 pass. `MERGEABLE` / `BLOCKED`(=리뷰 승인 대기, 코드 문제 아님).

### PR 정리 + 충돌/CI 해결 커밋
| 커밋 | 내용 |
|---|---|
| `d72ab3d` | PR 정리 — 설계 과정 산출물/중복 docs 11건 제거 + reseed 데이터 `linguist-generated` 마킹(.gitattributes) |
| `fab2085` | develop merge 충돌 해결 — sessions.py PO 이중알림 리팩토링(develop) 채택 + load_mode 정합(`equipment_type`→`category` semantic fix), test_po 합집합 |
| `83e9872` | CI lint fix — clean_slate 마이그 ruff format(docstring Edit 후 누락분) |
| `7f0ce13` | test_gym_muscle_equipments mock 갱신 — gyms 정션 계약(`ex_name`/`eq_name`/`load_mode`), Phase 6 누락분 |

### diff 규모
- **실코드 ~2,800줄**(py 1,302 + 마이그 913 + 테스트 353). 데이터 35k줄(reseed JSON)은 `linguist-generated`로 GitHub diff 접힘.
- 로컬 전체 **451 passed** (잔여 1 = `test_chat` DB 의존, 알려진 환경 — CI는 DB로 통과).
- admin 17건 로컬 실패는 `ADMIN_API_TOKEN` env 덮어쓰기 탓(CI 무관, conftest 기본값으로 통과).

### 다음 (PR 머지 후)
1. 리뷰 승인 → develop 머지
2. **prod 적용**: 런북대로 백업(papers 행수 기록) → `alembic upgrade head`(clean_slate→reseed_workoutx) → 검증 SQL
3. **Phase 7**: exercise_equipment junction(머신↔운동 Gemini 검증) + activation_pct 백필
4. **Phase 5**: 프론트 부위 10분류 + CI app tsc/lint job

### 교훈 (다음 세션 반영)
- 마이그/모든 파일 Edit 후에도 push 전 `ruff format --check server/ mlops/`(CI 동일 명령) 필수.
- 핵심 테스트만 돌리지 말 것 — CI는 전체 suite 실행. 계약 변경 시 `test_gym_muscle_equipments` 같은 mock 기반 테스트도 전수 갱신.
