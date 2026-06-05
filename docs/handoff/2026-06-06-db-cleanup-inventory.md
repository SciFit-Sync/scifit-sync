# DB 정비 마스터 인벤토리 — "지금 고쳐야 하는 데이터 전부"

> 작성 2026-06-06 · 대상 = **진짜 prod = Supabase `hnwegx`** (read-only 실측 기반)
> 목적: 운동-중심 재설계 **"정리 먼저 → 구조 변경 carry-over"** 전략의 **데이터 정리 단계** 백로그.
> 이 파일 하나로 흩어진 어제 감사 산출물(아래 §참조파일)을 통합한다. 5개 품질 게이트 기준으로 분류.

---

## 0. prod 핵심 수치 (스냅샷)

| 항목 | 값 |
|---|---|
| exercises | 1,401 |
| equipments | 178 |
| exercise_equipment_map(eem) | 26,102 (런타임 미사용, PR-5 DROP 예정) |
| live 루틴 (workout_routines) | 16~20 (pre-launch, blast≈0) |
| default_equipment_id 보유 운동 | 884 |
| muscle_groups | 21 → 26 (PR #287 정규화) |

**전제**: pre-launch — 보존할 사용자 데이터 거의 없음. 더러운 건 전부 레퍼런스/시드 데이터.

---

## 1. 상태 범례 & 마스터 체크리스트

- ✅ **PR 있음(미머지)** — 이미 수정 마이그레이션 작성됨, 머지·배포만 남음
- 🔧 **지금 고쳐야 함** — 미착수 또는 이 브랜치 진행 중. **데이터 정리 단계의 실제 작업**
- ⏸️ **후속 보류** — 별도 PR(파괴적/blast 큼 → 백업+허가 게이트)
- ⚪ **품질 백로그** — 기능영향 0, catalog/UX 차원

| # | 항목 | 게이트 | 규모 | 상태 | 담당 PR/브랜치 |
|---|---|---|---|---|---|
| A | default_equipment_id 오배정 | G3/G4 | 553 + 63 | 🔧 **지금** | `fix/jingyu/default-equipment-remap` (이 브랜치) |
| B | equipment_muscles garbage (팔 3기구) | G2 | 3기구 | ✅ PR #284 | `fix/jingyu/arm-equipment-muscles-fix` |
| C | equipment_muscles 결손 (arms 등) | G2 | ~103/130 | ✅ PR #287 ③ (부분) + 🔧 잔여 | `eqmuscle_deficit_backfill` |
| D | exercise_muscles primary 결손 + activation% | G1 | 1355운동 | ✅ PR #287 ② | `seed_muscle_activation` |
| E | muscle_groups 드리프트(사람이름 8+UpperBack) | G1 전제 | 8+1 | ✅ PR #287 ① | `normalize_muscle_groups` |
| F | 기구 중복 (lat pulldown×5 등 26종/60행) | G5 | 60행 | ⏸️ 후속 | dedup PR (DELETE 게이트) |
| G | 정본 generic 중복 (Dumbbell/Barbell/Smith) | G5 | 4행 | ⏸️ 후속 | dedup PR (A 이후) |
| H | 기구 name_en 결손 101 / 무사진 77 | ⚪ | 101/77 | ⚪ 백로그 | 멱등 UPDATE |
| I | 테스트/mock gym·user·제보 | ⚪ | gym3+user3 | ⏸️ 후속 | DELETE 게이트 |
| J | WorkoutX 근육 번역 규칙 미결 2건 | G1 정책 | 2 결정 | 🔧 결정 필요 | (§J) |

**→ "지금 고쳐야 하는"의 핵심 = A (default 오배정) + C 잔여 + J 결정.** B/D/E는 PR #287/#284로 이미 처리됨(머지·배포 대기).

---

## 2. [A] 🔧 default_equipment_id 오배정 — 최대 임팩트 (이 브랜치)

> 상세 원본: `2026-06-05-exercise-equipment-mislink-audit.md`, `2026-06-05-freeweight-equipment-trace.csv`

### 2.1 근본원인
백필 쿼리 `DISTINCT ON(...) ORDER BY equipment_type, id`가 **type별 최소 UUID**를 tie-break로 골랐고, 그 최소 UUID가 하필 특수/보조 기구라 547운동이 garbage 허브로 떨어짐.

### 2.2 garbage 허브 2개

| 기구 | id | type | 잘못 묶인 운동 | live 사용 |
|---|---|---|---|---|
| **EZ 바** | `32f43f66-12af-4071-8ca3-daa0ef753d22` | barbell (bar=10) | **177** | 0 |
| **어시스티드 풀업 머신** | `c323aec6-a872-4eff-94dc-f247e3dbb1a0` | bodyweight (assist=true) | **376** | 0 |

### 2.3 판정 분포 (547 verdict)
| verdict | 건수 |
|---|---|
| real_mislink | 515 (high 345 / med ~149 / low ~21) |
| false_positive | 28 (손대면 안 됨) |
| ambiguous | 4 |

### 2.4 정정 방향 (correct_type)
| 그룹 | 건수 | 현재(잘못) | 정정 후 |
|---|---|---|---|
| G1 맨몸/밴드/스트레칭/체조 | 385 | Assisted Pull-up Machine | **Bodyweight** |
| G2 바벨 컴파운드 | 118 | EZ Bar (10kg) | **Barbell** (20kg) |
| G3 dumbbell 무default | 10 | (없음) | **Dumbbell** |
| G4 머신/Lever/treadmill | 18 | 오타입 | **NULL** |
| + 무default 프리웨이트 백필 | 63 | NULL | 이름추론 generic |

### 2.5 정본 generic 타깃 (ID 하드코딩 금지 — name lookup)
| type | id | lookup 조건 |
|---|---|---|
| barbell | `f970fcc9-53e4-5c3c-9faf-24baa5105448` | name_en='Barbell' AND name='Barbell' AND bar_weight=20 |
| dumbbell | `a0b9376d-c6b1-5ea9-bb64-91b11560deae` | name_en='Dumbbell' AND name='Dumbbell' (v5, seed) |
| bodyweight | `57d1b189-30be-5316-8979-a1cf5db95946` | name_en='Bodyweight' AND name='맨몸' AND has_weight_assist=false |

### 2.6 🔴 구현 게이트 (절대 준수) — STEP A CASE 결함
정비안 §5.2 확정 결함: `WHERE default IN (EZ Bar, Assisted)`가 EZ Bar isolation **69개**(`Barbell Curl`, `Skull Crusher`, `French Press`, `Upright Row` 등)를 잡는데, barbell 제외절에 걸려 **ELSE→bodyweight로 오변환**됨. → load_calc이 `bar+added` 대신 `body_weight+added`.
**처방: CASE에 isolation 분기를 barbell보다 먼저 추가** (curl/extension/skull/french press/wrist curl/pullover/upright row → canon_barbell 또는 EZ Bar 유지). ELSE는 "장비 키워드 없는 순수 맨몸"에만.

### 2.7 탐지 SQL (게이트 G3 — 0건이어야 통과)
```sql
-- garbage 허브 잔존 (정정 후 0 기대)
SELECT count(*) FROM exercises
WHERE default_equipment_id IN (
  '32f43f66-12af-4071-8ca3-daa0ef753d22',   -- EZ Bar
  'c323aec6-a872-4eff-94dc-f247e3dbb1a0');  -- Assisted Pull-up Machine
```

---

## 3. [B][C] equipment_muscles — garbage(완료) + 결손(잔여)

> 상세: `2026-06-05-arm-equipment-muscles-followups.md`

### 3.1 ✅ [B] garbage 3기구 — PR #284 처리됨
| 기구 | id | 문제 | 교정 |
|---|---|---|---|
| Cable (Machine Lat Pulldown) | `bf3d0dde-84e3-...` | 5 primary garbage(triceps 포함) | lat primary로 |
| Cable (Machine Lat Pulldown) | `e94bec5c-a634-...` | 동일 | lat primary로 |
| Assisted Dip/Chin | `2ca108c5-6153-...` | 라벨='Cable Triceps Pushdown' 불일치 | triceps primary 수용 + 복합 정의 |

→ **이게 "팔 루틴에 랫풀다운" 버그의 직접 원인.** PR #284 + 커밋 f6b4d9f로 처리.

### 3.2 🔧 [C] 결손 — 잔여 작업
- `equipment_muscles` 전체 ~130개 중 27개(21%)만 채워짐. **category=arms 기구 16/17개 arm-primary 결손**.
- PR #287 ③ `eqmuscle_deficit_backfill`가 arms 18 결손 백필 → **잔여는 movement_label_en JOIN 방식으로 추가 백필** 필요.
- **제약**: `movement_label_en → exercises.name_en` JOIN만 (eem 집계 금지 — garbage 원인). muscle_group_id 하드코딩 금지(prod는 uuid5 아님 → JOIN 해석).

### 3.3 탐지 SQL (게이트 G2)
```sql
-- (a) 기구당 primary 과다 (N=2 초과 = garbage 의심)
SELECT equipment_id, count(*) FROM equipment_muscles
WHERE involvement='primary' GROUP BY 1 HAVING count(*) > 2;
-- (b) category=arms 기구 중 primary 0건 (결손)
SELECT e.id, e.name FROM equipments e
WHERE e.category='arms'
  AND NOT EXISTS (SELECT 1 FROM equipment_muscles m
                  WHERE m.equipment_id=e.id AND m.involvement='primary');
```

---

## 4. [D][E] 근육 매핑 + muscle_groups — PR #287 처리됨

### 4.1 ✅ [E] muscle_groups 드리프트 — `normalize_muscle_groups`
hnwegx muscle_groups에 사람이름 슬러그 8 + "Upper Back" 드리프트 → 표준 슬러그 정규화 + 신규 5종 = **26그룹**. (유일했던 스키마 드리프트, #287이 해소)

### 4.2 ✅ [D] exercise_muscles + activation% — `seed_muscle_activation`
1355운동 exercise_muscles + Gemini EMG activation% (`server/alembic/data/muscle_activation_seed.csv` 3893행).

### 4.3 탐지 SQL (게이트 G1)
```sql
-- primary 근육 0개인 운동 (유산소 29 제외하면 0 기대)
SELECT e.id, e.name_en FROM exercises e
WHERE NOT EXISTS (SELECT 1 FROM exercise_muscles m
                  WHERE m.exercise_id=e.id AND m.involvement='primary');
```

---

## 5. [F][G] ⏸️ 기구 중복 — 후속 dedup PR (blast 큼, DELETE 게이트)

> §A(default 정정) 완료 **후** 별도 PR. DELETE/ALTER = CLAUDE.md 절대금지 → 백업+명시 허가 필수.

### 5.1 [F] 중복명 26종/60행
lat pulldown ×5, hack squat ×4, leg extension ×4, smith machine ×2 등. → 물리 기구 1대 = 1행으로 dedup (단, 재설계의 "머신↔동작 정션"이 들어오면 일부는 동작 분리로 해소).

### 5.2 [G] 정본 generic 중복 (재포인트 후 삭제)
| 단계 | 대상 | 작업 | blast |
|---|---|---|---|
| Smith 타입픽스 | `fe005947` | type barbell→machine, bar_weight=15 재검토 | ~0 |
| Smith orphan 삭제 | `f6fe186b` (name_en NULL, gym=0) | gym_equipments 참조 0 확인 후 DELETE | ~0 |
| Dumbbell dedup | `6eff9e86`(v4, 덤벨, 293 default) → `a0b9376d`(v5) | 재포인트 후 삭제. **단일 트랜잭션** | **최대** |
| Barbell dedup | `90ea9d0a`(Olympic, 16 default, 테스트gym, rex 4) → `f970fcc9` | 둘 다 bar=20 무회귀. 물리 별개 바 보유 확인 후 | 중 |
| unique 제약 | generic row에 `(name_en, equipment_type)` unique | ad-hoc v4 generic 재삽입 차단 (재발 방지) | 신규 |

### 5.3 over-mapping 메모
풀업바 `fd80d7e6`·딥스바 `d7631d75`(더찬스짐): default_for 0이나 eem 377/379 과매핑 — 런타임 미사용(eem PR-5 DROP)이라 정리 불요.

---

## 6. [H] ⚪ 기구 데이터 품질 (기능영향 0)

> 상세: `2026-06-05-equipment-data-full.csv` (178 기구 × 24컬럼)

- **name_en 결손 101** — seed CSV엔 있음 → 멱등 UPDATE 복원 가능
- **무사진 77** — 제네릭 20 전부 + 브랜드 머신 다수 (앱 사진 보강 거리)
- **미참조 131** — gym/루틴 미사용 (catalog 대기)
- **결정 보류**: 기구 한글화 범위 (101만 vs 영어 158 전부) — 대부분 영어가 seed 규약이라 신중

---

## 7. [I] ⏸️ 테스트/mock 데이터 — DELETE 게이트

| 종류 | 내용 |
|---|---|
| 테스트 gym 3 | `스포애니 강남점`(kakao=12345678 가짜, 기구 0), `테스트 헬스장` ×2(기구 3·1) |
| 테스트 user 3 | `홍길동`(john123@hufs), `@test.com`(taehyun.dev) 등 |
| 데모 제보 | equipment_suggestions "레그 프레스 Pro" 1, equipment_reports 1 |

⚠️ prod DELETE → 명시 허가 + 백업 + 연관 루틴 소유 확인 선행.

---

## 8. [J] 🔧 WorkoutX 근육 번역 규칙 — 미결 결정 2건

> 상세: `2026-06-04-workoutx-muscle-mapping-gaps.md`, `2026-06-05-workoutx-1283-mapping.csv` (3694행)

대부분 결정됨(어깨→이름추론, 유산소 skip, 미보유근육 drop, 뭉친근육→대표1개). **남은 결정 2건:**
1. **어깨(Delts) 143개 기본값** — 이름으로 못 가리면 측면 삼각근? (제안 OK 여부)
2. **Upper Back 88개 기본** — 능형근 vs 승모근? **택1 필요**

---

## 9. 품질 게이트 통과 기준 (구조 변경 진입 전 0건 검증)

| 게이트 | 조건 | 상태 |
|---|---|---|
| **G1** primary 근육 결손 = 0 (유산소 제외) | §4.3 SQL | ✅ #287 후 |
| **G2** 기구당 primary ≤ 2 (복합 화이트리스트 예외) & arms 결손 = 0 | §3.3 SQL | 🔧 #287+잔여 |
| **G3** garbage 허브 default = 0, orphan default = 0 | §2.7 SQL | 🔧 [A] |
| **G4** 맨몸이 바벨/머신 가리킴 = 0 (분류 모순) | [A]에 포함 | 🔧 [A] |
| **G5** 물리 기구 중복 정리 완료 | §5 | ⏸️ 후속 |

> **결정 필요**: G5(기구 중복)를 정리 단계 게이트에 **포함**할지, 아니면 재설계의 "머신↔동작 정션" 도입 때 같이 해소할지. dedup이 blast가 커서 **재설계와 묶는 게 효율적**일 수 있음(중복 일부는 동작 분리로 자연 해소).

---

## 10. 참조 파일 (docs/handoff/, untracked)

| 파일 | 내용 |
|---|---|
| `2026-06-05-exercise-equipment-mislink-audit.md` | [A] 547 판정 + 정비안 SQL 골격 + §5.2 결함 |
| `2026-06-05-freeweight-equipment-trace.csv` | garbage 허브 + 정본 generic 9개 프로필 |
| `2026-06-05-equipment-data-full.csv` | [H] 178 기구 × 24컬럼 (issues 플래그) |
| `2026-06-05-prod-db-state-and-cleanup.md` | prod 정체 + 백로그 원본 |
| `2026-06-05-arm-equipment-muscles-followups.md` | [B][C] 팔 근육 garbage/결손 |
| `2026-06-04-workoutx-muscle-mapping-gaps.md` | [J] 번역 규칙 5건 |
| `2026-06-05-workoutx-1283-mapping.csv` | WorkoutX 근육 매핑 1283행 |
| `server/alembic/data/muscle_activation_seed.csv` | [D] activation% 시드 3893행 |

## 11. 메모리 교차참조
- `project_exercise_equipment_mislink_audit` — [A] 547 전수감사
- `project_arm_routine_fullbody_diagnosis` — [B] 팔→전신 버그
- `project_prod_migration_drift` — 배포 드리프트
- `project_equipment_centric_pr_chain` — PR #283/#284/#287, PR-5
- `project_real_prod_db_identity` — 🔴 prod=hnwegx
- `reference_prod_readonly_inspection` — prod read-only 절차
