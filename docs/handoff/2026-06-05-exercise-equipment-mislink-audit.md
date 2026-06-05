# 운동↔기구 연결 오배정 — 최종 종합·정비안 (staff engineer 핸드오프)

> 작성일: 2026-06-05
> 대상 DB: **진짜 prod = Supabase `hnwegx`** (read-only 검증)
> 입력: 547 판정(verdict) + 중복기구 감사 + eem 근본원인 감사
> 산출물 목적: 단일 멱등 Alembic 마이그레이션 **스펙**(이 문서에서는 파일 생성 X)

---

## 0. TL;DR (헤드라인)

- prod 운동 1,401개 중 **547개**가 잘못된 `default_equipment_id`를 가짐. 근본원인은 백필 쿼리의 `DISTINCT ON ... ORDER BY equipment_type, id` **tie-break가 type별 최소 UUID를 골랐고**, 그 최소 UUID가 하필 "특수/보조" 기구(EZ Bar bar=10, Assisted Pull-up Machine `has_weight_assist=true`)였다.
- 두 garbage 허브에 운동이 몰림: **Assisted Pull-up Machine 376개 / EZ Bar 177개** (합 553, 884 default 중 대부분). 둘 다 **실루틴 사용 0건**.
- **라이브 영향 ≈ 0** (오배정 후보 547개 중 live 루틴에 엮인 건 `Good Morning` 1개, 그나마 정상). 그러나 사용자가 프리웨이트 루틴을 생성/기록하는 즉시 `load_calc`가 `body_weight − stack`(맨몸을 어시스트 머신으로) 또는 bar 10kg 과소(바벨을 EZ바로) 오류를 낸다 → **잠재 폭탄, 출시 전 반드시 수정**.
- 수정 전략은 **[B] eem 무시 + 이름추론 타입 → 정본 generic 직접 재산정** (eem은 PR-5에서 DROP 예정, 런타임은 `default_equipment_id`만 읽음). 단일 멱등 마이그레이션으로 해결 가능.

---

## 1. 판정(verdict) 검증·분류

### 1.1 전체 분포 (내부 정합성 검증 완료)

`severity 합(345+53+149)=547`, `correct_type 합(385+10+18+16+118)=547` — 두 축 모두 총 547과 일치, 누락/중복 없음.

| verdict | 건수 | 비중 |
|---|---:|---:|
| real_mislink | **515** | 94.1% |
| false_positive | **28** | 5.1% |
| ambiguous | **4** | 0.7% |
| **합계** | **547** | 100% |

### 1.2 real_mislink severity 분해

real_mislink 515건을 severity로 쪼개면 (high 345는 전부 real_mislink, low 53·med 149에서 FP/ambiguous를 제외):

| severity | real_mislink | 설명 |
|---|---:|---|
| **high** | **345** | 맨몸/밴드/스트레칭/체조 운동이 Assisted Pull-up Machine(assist=true)에 묶임 → `load_calc`가 `body_weight − stack` 산출 (음수/garbage). 가장 위험. |
| **med** | **149** | (a) 바벨 컴파운드가 EZ Bar(10kg)에 묶임 → bar 10kg 과소, (b) Smith/Lever 머신·default 없는 dumbbell/weighted 운동. 부하 왜곡이되 부호 오류는 아님. |
| **low** | **21** | weighted/kettlebell/stability-ball 류로 `load_calc` 실제 영향 미미(예: Jump Rope = body_weight+0). |
| **real 합** | **515** | |

> 검증 메모: `by_severity`의 low 53 중 **28건은 false_positive(low)**, **4건은 ambiguous(low 2 + 그 외)**, 나머지 ~21건이 real_mislink(low). med 149 중 일부는 ambiguous(barbell med). 즉 real_mislink high=345, med≈149, low≈21로 515에 수렴 — high 345가 단연 다수이며 가장 위험하다.

### 1.3 correct_type별 (수정 방향)

| correct_type | 건수 | 의미 |
|---|---:|---|
| **bodyweight** | 385 | 맨몸/밴드/스트레칭/체조/weighted-bodyweight → 정본 Bodyweight generic으로 |
| **barbell** | 118 | EZ Bar/특수바에 묶인 올림픽바 컴파운드 → 정본 Barbell(20kg)로 |
| **machine_null** | 18 | Lever(plate-loaded)/Run(treadmill)/Seated Calf/Inverse Leg Curl(cable) → **NULL** (정본 machine generic 부재) |
| **keep** | 16 | false_positive — 현재 default가 정당, 손대지 말 것 |
| **dumbbell** | 10 | default 없는 dumbbell 운동 → 정본 Dumbbell generic으로 |

### 1.4 false_positive 28건 — 왜 과탐이었나 (휴리스틱 한계)

감사 휴리스틱은 "default 기구의 type/assist 속성"과 "운동 이름 추론 type"의 불일치를 의심 신호로 잡았다. 아래 두 패턴이 정당함에도 깃발이 섰다.

**(A) EZ Bar가 정당한 운동인데 "specialty_bar_on_compound"으로 오탐 (keep 16건의 다수)**
- 예: `EZ Bar Standing French Press`, `EZ-bar Close-grip Bench Press`, `Barbell Reverse Grip Skullcrusher`, `Ez Barbell Seated Curls`, `Finger Curls`, `Ez Bar Lying Bent Arms Pullover`, `Barbell Upright Row V.3`
- **한계**: 휴리스틱은 "EZ Bar default = 무조건 의심"으로 처리했지만, **컬(curl)/스컬크러셔/프렌치프레스/클로즈그립/업라이트로우**는 EZ Bar가 손목 부담을 줄이는 *정본 구현*이다. 이름에 "Barbell"이 들어가도 트라이셉/이두 isolation은 EZ Bar가 표준.
- **교훈**: type-mismatch만으로 판단 금지. "운동 종류(컴파운드 vs isolation)"를 함께 봐야 함.

**(B) Assisted-machine 운동이 NULL이어야 정상인데 "freeweight_ex_no_default"로 묶이거나 keep으로 재분류 (machine_null FP ~12건)**
- 예: `Assisted Pull-up`, `Assisted Standing Chin-up`, `Assisted Triceps Dip (kneeling)`, `Assisted Sit-up`, `Assisted Hanging Knee Raise`, `Assisted Wide-grip Chest Dip (kneeling)`
- **한계**: 이들은 `eem_types=['machine']`인 *진짜 어시스트 머신 전용* 운동. 정본 machine generic이 없어 NULL이 맞다. 휴리스틱은 "default가 비어/머신이면 freeweight로 채워야 한다"고 가정했으나 이 그룹은 freeweight 타깃을 주면 오히려 틀린다.
- **분류 처리**: 이들의 verdict는 false_positive지만 `correct_type=machine_null`로 표기 — "현재 NULL 또는 머신default가 정답"이므로 **마이그가 건드리지 않아야 한다**.

**(C) gym 컨텍스트 default가 정당 (keep)**
- `Hip Thrust`(=헬스장에선 바벨 로딩이 표준 → Olympic Barbell 20kg 정당), `Good Morning`(바벨 동작 → 20kg 정당)
- **한계**: 이름만 보면 "맨몸 가능"이라 의심됐으나, 헬스장 루틴 맥락에선 바벨이 표준.

### 1.5 ambiguous 4건 — 판단 보류, barbell/bodyweight generic이 최선

| 운동 | correct_type | 사유 |
|---|---|---|
| `Cambered Bar Lying Row` | barbell | 캠버드 바(특수 20kg급). 전용 구현 없어 barbell generic이 차선. |
| `Barbell Hack Squat` | barbell | 이름은 바벨(바닥 바벨 behind legs), inferred=machine 충돌. eem_types=barbell only → freeweight form likely → barbell 처리. |
| `Glute Bridge` | bodyweight | 기본형은 맨몸, 바벨 변형이 흔하나 별도 명명 안 됨 → 맨몸 default. |
| `Exercise Ball On The Wall Calf Raise` | bodyweight | 안정성 드릴. dumbbell add-on은 minor지만 방어 가능 → 맨몸. |

> 정책: ambiguous 4건은 **real_mislink와 동일 처리(이름추론 generic)**. 단 사후 재감사 리스트에 별도 표기해 사람이 한 번 더 본다.

---

## 2. "실제로 수정이 필요한가?" — 명확한 답

### 2.1 무엇을 (수정 대상)

| 그룹 | 건수 | 현재 잘못된 default | 정정 후 |
|---|---:|---|---|
| **G1. 맨몸/밴드/스트레칭/체조** | 385 | Assisted Pull-up Machine (assist=true) | **Bodyweight** generic |
| **G2. 바벨 컴파운드** | 118 | EZ Bar (bar=10kg) | **Barbell** generic (20kg) |
| **G3. dumbbell 무default** | 10 | (default 없음) | **Dumbbell** generic |
| **G4. 머신/케이블/Lever/treadmill** | 18 | bodyweight/barbell 오타입 | **NULL** |
| **합계 (수정)** | **531** | | |

### 2.2 왜 (load_calc 영향 메커니즘) — `server/app/services/load_calc.py`

```python
match equipment.equipment_type:
    case "cable" | "machine": return stack_kg / pulley_ratio + bar_kg
    case "barbell":           return bar_kg + (added or 0)
    case "dumbbell":          return added or 0
    case "bodyweight":
        if equipment.has_weight_assist: return body_weight - stack_kg   # ← G1 폭탄
        return body_weight + (added or 0)
```

- **G1 (가장 위험, high 345)**: 맨몸 푸시업이 `has_weight_assist=True`인 Assisted Pull-up Machine에 묶이면 `body_weight − stack_kg` 분기로 빠진다. 사용자가 stack을 입력하면 **음수/엉터리 effective weight** → 1RM·PO·권장중량 전부 오염.
- **G2 (med 118)**: 바벨 벤치/스쿼트/데드가 EZ Bar(bar=10)에 묶이면 `barbell` 분기는 맞지만 bar가 **10kg 과소** → effective weight 10kg 저평가 → PO 증가량/1RM 왜곡.
- **G3 (med 10)**: dumbbell 운동에 default 없음 → `load_calc` 호출 자체가 기구를 못 찾아 계산 불가/예외.
- **G4 (high/med 18)**: Lever(plate-loaded machine)·treadmill run이 bodyweight/barbell로 잘못 들어가 machine 분기를 못 타고 garbage. machine generic이 없으니 NULL이 안전(런타임이 NULL이면 gym 기구 폴백/사용자 선택).

### 2.3 우선순위 (severity × blast)

- **현재 blast ≈ 0**: 두 garbage 허브(EZ Bar/Assisted) `rex_used=0`. live 루틴 16개에 엮인 오배정 후보는 `Good Morning` 1개뿐이고 그것도 정상(false_positive). **즉 지금 당장 깨진 사용자 데이터는 없다.**
- **그러나 잠재 severity 최상**: 출시 후 사용자가 프리웨이트 루틴을 만드는 순간 G1/G2가 즉시 발동. 출시 전 수정이 가장 비용 낮은 시점.
- **권장 우선순위**: G1(high 385) ≥ G4(머신 부호오류 18) > G2(bar 과소 118) > G3(무default 10).

### 2.4 안 고쳐도 되는 것 (수정 제외)

- **false_positive 28건** (keep 16 + machine_null-as-keep 12): EZ Bar 정당 isolation, 진짜 어시스트 머신 운동, gym-context 바벨. **마이그가 절대 건드리면 안 됨** — WHERE 가드로 보호.
- **eem 26,102행 자체**: PR-5에서 DROP 예정. 런타임은 `default_equipment_id`만 읽으므로 eem 정제는 무의미. 손대지 말 것.
- **band 39개의 type 신설**: band equipment_type이 DB에 없음. 별도 도메인 결정 전까지 bodyweight 폴백(자유 부하라 합리적).

---

## 3. 정비안 — 단일 멱등 Alembic 마이그레이션 설계 스펙

> ⚠️ **이 단계에서는 마이그레이션 파일을 생성하지 않는다. 아래는 스펙·SQL 골격만.**
> 패턴 준거: `server/alembic/versions/20260605_recover_default_equip_bodyweight.py` (멱등 가드 + asyncpg 규칙).

### 3.1 정본 generic 타깃 — ⚠️ 입력 간 충돌 해소

세 입력이 dumbbell/barbell에서 엇갈린다. 결론:

| type | 본 정비안 채택 ID | 근거 |
|---|---|---|
| **barbell** | `f970fcc9-53e4-5c3c-9faf-24baa5105448` (`'Barbell'`, v5, 20kg) | 태스크 §3 명시 + 중복기구 감사(입력3)가 keep으로 지정. **v5 결정적**(alembic 재실행 재현). EZ Bar 아님. |
| **dumbbell** | `a0b9376d-c6b1-5ea9-bb64-91b11560deae` (`'Dumbbell'`, v5) | 중복기구 감사(입력3)가 keep으로 강력 권고(v5 결정적, gym-독립). ※입력4 SQL은 v4 `6eff9e86`을 name으로 lookup했으나, 그 v4 row는 random·gym-bound라 정본 부적격. **본 정비안은 v5 `a0b9376d` 채택**(아래 3.4 충돌 노트 참조). |
| **bodyweight** | `57d1b189-30be-5316-8979-a1cf5db95946` (`'Bodyweight'`, v5) | 세 입력 모두 일치. assist=false 올바름. Assisted Pull-up Machine 아님. |

**ID 하드코딩 대신 `name_en`+`name`으로 lookup**해 변수에 담는다(환경 간 UUID 불일치 차단). v5 generic은 `(name_en, name)` = (`'Barbell'`,`'Barbell'`) / (`'Dumbbell'`,`'Dumbbell'`) / (`'Bodyweight'`,`'맨몸'`)으로 v4 dup과 구별 가능. lookup 결과가 하나라도 NULL이면 `RAISE EXCEPTION`으로 전체 롤백.

### 3.2 재산정 로직 (CASE 우선순위 — 머신부터 거른다)

판정 결과(verdict의 correct_type)를 1차 진실로 쓰되, 마이그는 prod에서 멱등 실행돼야 하므로 **garbage 허브에 묶인 행 + 무default 프리웨이트 행**만 좁혀 잡고 이름패턴 CASE로 분기:

1. **machine/cable/lever/treadmill → NULL** (가장 먼저): `~ '(lever|hack squat|front lever|back lever|^run$|run \(equipment\)|seated calf|inverse leg curl.*(cable|pull-up))'`
2. **dumbbell → Dumbbell generic**: `~ 'dumbbell'`
3. **barbell 컴파운드 → Barbell generic**: `~ '(barbell|deadlift|squat|clean|snatch|good morning|overhead press|bench press|thruster|landmine|trap bar|power clean)'` — **단 EZ Bar 정당군 제외**: `AND name_en !~ '(french press|skullcrusher|curl|close.?grip bench|upright row|finger curl|pullover.*ez|anti.?gravity|jm (bench|press))'`
4. **그 외(맨몸/풀업/딥/레이즈/밴드/체조/weighted-bodyweight) → Bodyweight generic** (ELSE 폴백)

### 3.3 SQL 골격 (forward-only, 멱등, named-param 불요 — DO 블록 자체 실행)

```python
"""fix freeweight default_equipment_id misassignment (EZ Bar / Assisted Pull-up Machine)

Revision ID: <gen, 32자 이내>
Down revision: 20260605_recover_default_equip_bodyweight
"""
from alembic import op

def upgrade():
    op.execute("""
    DO $$
    DECLARE
        garbage_barbell  uuid := '32f43f66-12af-4071-8ca3-daa0ef753d22';  -- EZ Bar (bar=10)
        garbage_assist   uuid := 'c323aec6-a872-4eff-94dc-f247e3dbb1a0';  -- Assisted Pull-up Machine (assist=true)
        canon_barbell    uuid;
        canon_dumbbell   uuid;
        canon_bodyweight uuid;
    BEGIN
        -- 정본 generic을 name으로 lookup (v5 결정적 generic 식별)
        SELECT id INTO canon_barbell    FROM equipments WHERE name_en='Barbell'    AND name='Barbell'    AND equipment_type='barbell'    AND bar_weight=20 LIMIT 1;
        SELECT id INTO canon_dumbbell   FROM equipments WHERE name_en='Dumbbell'   AND name='Dumbbell'   AND equipment_type='dumbbell'   LIMIT 1;
        SELECT id INTO canon_bodyweight FROM equipments WHERE name_en='Bodyweight' AND name='맨몸'        AND equipment_type='bodyweight' AND has_weight_assist=false LIMIT 1;

        IF canon_barbell IS NULL OR canon_dumbbell IS NULL OR canon_bodyweight IS NULL THEN
            RAISE EXCEPTION 'canonical generic missing (barbell=%, dumbbell=%, bodyweight=%)',
                canon_barbell, canon_dumbbell, canon_bodyweight;
        END IF;

        ----------------------------------------------------------------
        -- STEP A) garbage 허브에 묶인 운동 재산정
        --   WHERE 가드 = 멱등 핵심: 정정되면 default가 정본 ID로 바뀌어 재실행 시 no-op
        ----------------------------------------------------------------
        UPDATE exercises e
        SET default_equipment_id = CASE
            WHEN lower(coalesce(e.name_en,'')) ~ '(lever|hack squat|front lever|back lever|^run$|run \(equipment\)|seated calf|inverse leg curl.*(cable|pull-up))'
                THEN NULL
            WHEN lower(coalesce(e.name_en,'')) ~ 'dumbbell'
                THEN canon_dumbbell
            WHEN lower(coalesce(e.name_en,'')) ~ '(barbell|deadlift|squat|clean|snatch|good morning|overhead press|bench press|thruster|landmine|trap bar|power clean)'
                 AND lower(coalesce(e.name_en,'')) !~ '(french press|skullcrusher|curl|close.?grip bench|upright row|finger curl|anti.?gravity|jm (bench|press))'
                THEN canon_barbell
            ELSE canon_bodyweight
        END
        WHERE e.default_equipment_id IN (garbage_barbell, garbage_assist);

        ----------------------------------------------------------------
        -- STEP B) default 없는 프리웨이트 운동 63개 백필 (freeweight_ex_no_default)
        --   54 bodyweight + 7 dumbbell + 2 barbell. 이름추론으로 채움.
        --   WHERE default IS NULL 가드 → 멱등.
        ----------------------------------------------------------------
        UPDATE exercises e
        SET default_equipment_id = CASE
            WHEN lower(coalesce(e.name_en,'')) ~ 'dumbbell' THEN canon_dumbbell
            WHEN lower(coalesce(e.name_en,'')) ~ '(barbell|deadlift|squat|clean|snatch|good morning|bench press)' THEN canon_barbell
            ELSE canon_bodyweight
        END
        WHERE e.default_equipment_id IS NULL
          AND e.id IN (
            -- 63개 후보 id를 명시 픽스처로 IN 절에 박는다 (candidates.json의
            -- issues LIKE 'freeweight_ex_no_default%' 추출). 전체 NULL을 무차별로
            -- 채우지 않도록 화이트리스트로 제한 → 머신/케이블 운동 보호.
            '...'::uuid /* , ... 63개 */
          );

        RAISE NOTICE 'off-garbage=% , backfilled-null exists',
            (SELECT count(*) FROM exercises WHERE default_equipment_id IN (canon_barbell, canon_dumbbell, canon_bodyweight));
    END $$;
    """)

def downgrade():
    # 비가역(forward-only): 원본 garbage 매핑은 결함 상태 → 복원 가치 없음.
    # 롤백 필요 시 마이그 전 exercises(id, default_equipment_id) 스냅샷 백업 권장.
    pass
```

### 3.4 ⚠️ 충돌 노트 (반드시 PR 리뷰에서 결정) — dumbbell 정본 ID

- **태스크 §3**은 dumbbell 정본을 `6eff9e86`(v4)로 명시. **중복기구 감사(입력3)**는 `6eff9e86`을 **remove 대상**으로, `a0b9376d`(v5)를 keep으로 지정. 모순.
- **본 정비안 권고**: **v5 `a0b9376d`를 정본으로 채택**. 이유 — (1) v5는 결정적(alembic 재실행 재현), (2) v4 `6eff9e86`은 gym-bound·random이라 generic 부적격, (3) default_for 293(=mis-assignment fanout)은 merit가 아니라 정리 대상.
- **단, 절대 안전조건**: dumbbell dedup(3.5의 STEP D)을 **이 마이그 전에** 끝내 `6eff9e86`→`a0b9376d` 재포인트를 완료했거나, 두 row가 공존하는 동안에는 lookup이 v5만 잡도록 `name='Dumbbell'`(v4는 `name='덤벨'`) 조건으로 구분. 이 name 구분이 두 row 공존 상태에서도 정확히 v5만 선택함을 prod에서 확인 후 적용.

### 3.5 중복기구/Smith 타입오류 정리 — **별도 마이그레이션, blast 경고**

dedup은 default 재포인트 + gym_equipments + routine_exercises 갱신이 얽혀 blast가 크므로 **§3.3 마이그와 분리한 후속 PR**로 처리한다. 순서: (3.3 default 정정) → (Smith 타입픽스) → (dedup).

| 단계 | 작업 | blast |
|---|---|---|
| **STEP C. Smith 타입픽스** | survivor `fe005947` `equipment_type barbell→machine` (Smith는 가이드 랙). bar_weight=15 재검토. orphan `f6fe186b`(name_en NULL, gym=0) 삭제 전 gym_equipments 참조 0 확인 | 거의 0 (default_for=0) |
| **STEP D. Dumbbell dedup** | `6eff9e86`(293 default + gym 2 + rex 9) → `a0b9376d` 재포인트 후 삭제. **단일 트랜잭션**: UPDATE refs(exercises.default_equipment_id, gym_equipments, routine_exercises) → DELETE | **최대** (293 default 재포인트) |
| **STEP E. Barbell dedup** | `90ea9d0a` Olympic Barbell(16 default + gym 1 + rex 4) → `f970fcc9` 재포인트 후 삭제. 둘 다 bar=20 → load_calc 무회귀. **단, 어떤 gym이 물리적으로 별개 바를 보유하는지 삭제 전 확인** | 중 (16+4 재포인트) |
| **STEP F. unique 제약** | generic/gym-독립 row에 `(name_en, equipment_type)` unique 또는 seed-only invariant 추가 → 향후 ad-hoc v4 generic 재삽입 차단 (근본 재발 방지) | 신규 제약 |

> ⚠️ **DELETE/ALTER는 CLAUDE.md 절대금지 대상** — dedup PR은 백업 확인 + 사용자 명시 허가 후 단일 트랜잭션으로만. 본 §3.3 default 정정 마이그에는 DELETE/ALTER가 없다(UPDATE only).

### 3.6 멱등성·asyncpg·forward-only 규칙

- **멱등성**: STEP A는 `WHERE default IN (garbage 2개)` 가드, STEP B는 `WHERE default IS NULL AND id IN (화이트리스트)` 가드. 두 번째 실행 시 모두 no-op.
- **asyncpg**: 위 골격은 `op.execute` 정적 SQL(DO 블록)이라 named param 불요. 만약 Python 측에서 동적 바인딩이 필요하면 `recover` 마이그 패턴대로 **named param(`:x`) + 명시 CAST(`(:x)::uuid`)** 사용, `statement_cache_size=0` 검증.
- **forward-only**: `downgrade()`는 `pass`(비가역). 안전 롤백 필요 시 마이그 전 `exercises(id, default_equipment_id)` CSV 스냅샷.
- **CLAUDE.md 정합**: Alembic 단독 관리, Supabase 대시보드 직접 수정 금지. revision id 32자 이내(과거 `8e3c625` 교훈).

---

## 4. 검증 계획

### 4.1 마이그 적용 후 재감사 쿼리 (read-only, verify-full TLS + `statement_cache_size=0`)

```sql
-- (1) garbage 허브 잔존 0 이어야 함
SELECT count(*) FROM exercises
WHERE default_equipment_id IN (
  '32f43f66-12af-4071-8ca3-daa0ef753d22',  -- EZ Bar
  'c323aec6-a872-4eff-94dc-f247e3dbb1a0'); -- Assisted Pull-up Machine
-- 기대: 0

-- (2) 정본 generic으로의 재배정 분포 (대략 G1 385 / G2 118 / G3 10)
SELECT eq.name_en, eq.equipment_type, eq.has_weight_assist, count(*) AS n
FROM exercises e JOIN equipments eq ON eq.id = e.default_equipment_id
WHERE eq.name_en IN ('Barbell','Dumbbell','Bodyweight')
GROUP BY 1,2,3 ORDER BY n DESC;

-- (3) machine_null 18개가 NULL인지
SELECT count(*) FROM exercises
WHERE lower(name_en) ~ '(lever|hack squat|front lever|back lever|^run|seated calf)'
  AND default_equipment_id IS NOT NULL;
-- 기대: 0 (또는 알려진 잔존만)

-- (4) false_positive 보호 검증: EZ Bar 정당 isolation이 그대로 EZ Bar인지
SELECT e.name_en, eq.name_en FROM exercises e JOIN equipments eq ON eq.id=e.default_equipment_id
WHERE e.name_en ~* '(french press|skullcrusher|curl|jm press)';
-- 기대: 여전히 EZ Bar (마이그가 안 건드림)

-- (5) live 루틴 무회귀: Good Morning default 불변
SELECT name_en, default_equipment_id FROM exercises WHERE name_en='Good Morning';
-- 기대: Olympic/Barbell 20kg 유지
```

### 4.2 load_calc 단위테스트 영향 (`server/app/services/load_calc.py` — 100% 커버리지 필수)

- 신규 케이스: (a) Bodyweight generic(assist=false) → `body_weight + added` 정상, (b) Barbell generic(bar=20) → `20 + added`, (c) Dumbbell generic → `added`, (d) NULL default → 호출부가 gym 기구/사용자선택 폴백하는지.
- 회귀: 기존 어시스트 머신(`Assisted Pull-up` 등 진짜 머신)은 여전히 `body_weight − stack` 정상 분기 — false_positive 보호 확인.

### 4.3 gym 프리웨이트 브라우즈/루틴생성 회귀 (런타임)

- `server/app/api/v1/routines.py`(프리웨이트 후보 971-1041, `_resolve_label` 1198-1258), `gyms.py`(611-644)가 `default_equipment_id`를 읽어 라벨/후보를 만든다.
- 시나리오: (1) 더찬스짐(equip_count=42)에서 맨몸 운동(푸시업) 루틴 생성 → 라벨 "Bodyweight", load_calc 정상. (2) 바벨 벤치 → "Barbell 20kg". (3) NULL default 운동 → gym 기구 폴백/사용자 선택 UI 정상.
- 빈/중복 gym 엣지케이스: 입력3이 지적한 equip_count=0 gym(스포애니/찬스짐)과 중복 '테스트 헬스장' 2개는 prod 제외/정리 확인(루틴-무기구 엣지케이스 차단).

---

## 부록 A. 근본원인 1줄 정리

> 백필 `DISTINCT ON(...) ORDER BY equipment_type, id`가 type별 **최소 UUID**를 골랐고, freeweight 중복등록 탓에 그 최소 UUID가 EZ Bar(bar=10)·Assisted Pull-up Machine(assist=true)이라 547개가 garbage로 떨어졌다. eem 26k 과매핑은 머신 노이즈일 뿐 원인이 아니다 — 따라서 eem 정제([A])가 아니라 정본 generic 직접 재산정([B])이 정답.

## 부록 B. 핵심 수치

| 항목 | 값 |
|---|---|
| prod 운동 / 기구 / eem / live 루틴 | 1,401 / 178 / 26,102 / 16 |
| default 보유 운동 | 884 |
| 오배정 후보(=547 판정) | 547 |
| real_mislink (high/med/low) | 515 (345 / ~149 / ~21) |
| false_positive / ambiguous | 28 / 4 |
| 수정 대상(G1~G4) | 531 (bodyweight 385 + barbell 118 + dumbbell 10 + machine_null 18) |
| garbage 허브 default_for | Assisted 376 / EZ Bar 177 (rex_used 0/0) |
| 현재 라이브 blast | ≈ 0 (Good Morning 1개, 정상) |

---

## 5. 리뷰 검증 결과 (reviewer 패스 — raw 데이터 대조, 2026-06-05)

> 종합 리포트(§0~4)를 prod raw 데이터(`/tmp/equip_audit/*.json`) + seed CSV에 대조 검증한 결과. **진단·근본원인·"수정 필요" 결론은 모두 타당**. 단, 정비안 §3.3 SQL 골격에 **구현 전 반드시 고쳐야 할 결함 1건**과 dumbbell 정본 **확정 증거**를 추가한다.

### 5.1 ✅ Dumbbell 정본 충돌 — 증거로 종결 (`a0b9376d` 채택 확정)
seed CSV(`mlops/data/equipments_seed.csv`) 직접 확인:
| id | ver | name | name_en | in_seed_csv |
|---|---|---|---|---|
| `a0b9376d…` | v5 | **`Dumbbell`** | `Dumbbell` | **True** ← 정본 |
| `6eff9e86…` | v4 | `덤벨` | `Dumbbell` | **False** ← ad-hoc 중복(293 오배정 흡수) |

- `a0b9376d`만 seed CSV에 존재 → `alembic upgrade head` 재현 가능한 진짜 generic. `6eff9e86`은 seed 밖 런타임/구seed 잔재. **§3.1·§3.4의 v5 채택 권고가 옳다 (확정, PR 리뷰 추가논의 불요).**
- 부수 확인: §3.3 SQL의 `WHERE name_en='Dumbbell' AND name='Dumbbell'` lookup은 **모호성 없음** — `6eff9e86`은 `name='덤벨'`(한글)이라 매칭 제외. 두 행 공존 상태에서도 v5만 정확히 선택됨.
- `57d1b189`(bodyweight) = `uuid5(NAMESPACE_DNS,"scifit-sync.equipment.bodyweight-generic")` 일치 확인 (name='맨몸'/name_en='Bodyweight').

### 5.2 🔴 정비안 §3.3 STEP A 결함 — EZ Bar 정당 isolation 69개가 Bodyweight로 오변환
STEP A는 `WHERE default IN (EZ Bar, Assisted)`로 **EZ Bar에 묶인 행 전부**(177개)를 잡는다. 그런데 CASE 분기에서:
- curl/skullcrusher/french press/extension/wrist curl/pullover/upright row 등은 barbell 분기의 `AND name !~ '(...curl...)'` 제외절에 걸려 **barbell이 안 됨**
- 머신·dumbbell 패턴도 아님 → **ELSE → `canon_bodyweight`로 떨어짐**

검증(prod 데이터): EZ Bar 묶인 운동 중 isolation 정당군 **69개 전부가 `bodyweight(ELSE)`로 분기** (예: `Barbell Curl`, `Skull Crusher`, `Ez Bar Standing French Press`, `Ez Barbell Incline Triceps Extension`, `Barbell Wide-grip Upright Row`).
→ 결과: 팔 isolation 69개가 맨몸으로 오변환되어 load_calc가 `bar+added` 대신 `body_weight+added` 계산. **이는 §4.1 검증쿼리 ④("EZ Bar 유지 기대")와 정면 모순.** 즉 정비안이 한 방향 오배정(EZ바 compound)은 고치면서 **반대 방향 오배정(EZ바 isolation→맨몸)을 새로 만든다.**

**수정 처방 (구현 시)**: STEP A CASE에 isolation 분기를 추가한다 — curl/extension/skull/french press/wrist curl/pullover/upright row 등 EZ바 정당 isolation은 **`canon_barbell`(또는 EZ Bar 유지)** 로 보내고, **절대 ELSE(bodyweight)로 흘리지 않는다.** ELSE 폴백은 "장비 키워드 없는 순수 맨몸"에만 적용되도록 좁힐 것. (참고: EZ Bar bar=10은 컬에는 물리적으로 맞으므로 "EZ Bar 유지"도 정당한 선택지.)

### 5.3 🟡 경미 — "수정 대상 531" 과대계상
§2.1/부록B의 "수정 대상 531"은 `machine_null 18`을 전부 포함하나, 그중 ~12개는 이미 default=NULL인 false_positive(STEP A의 `WHERE default IN (garbage)` 가드에 안 걸려 무변경). 실제 row-change 수 = garbage 묶인 553 + 무default 백필 63 중 화이트리스트분. 마이그 안전성엔 영향 없음(가드가 보호), 서술 카운트만 느슨함.

### 5.4 검증 종합
- **진단/근본원인/blast≈0/수정필요 결론**: 타당 (재현 확인).
- **정본 generic 3종**: `f970fcc9`(barbell20) · `a0b9376d`(dumbbell, seed) · `57d1b189`(bodyweight uuid5) — 확정.
- **구현 게이트**: §3.3 STEP A는 **5.2 처방 반영 후에만** 마이그 작성. ELSE→bodyweight 폴백이 EZ바 isolation 69개를 삼키지 않도록 isolation 분기 선행 필수.

---

## 6. 구현·검증 완료 (2026-06-06)

마이그레이션 **작성·검증 완료**. branch `fix/jingyu/default-equipment-remap`.

**파일**: `server/alembic/versions/20260606_remap_default_equipment.py`
- revision `20260606_remap_default_equip` ← `20260605_dipchin_compound`(현재 head). UPDATE only / forward-only / 멱등.
- §5.2 처방 반영: STEP A를 **hub-aware**로 재설계(EZ허브=바벨계열, Assisted허브=맨몸계열) → EZ 명시 isolation 분기를 ELSE보다 선행시켜 69개 오변환 차단. 정본 generic·garbage hub 모두 `name_en` 룩업(env-portable), canon 누락 시 `RAISE`(전체 롤백).

**재산정 결과 (prod 시뮬, STEP A 553건 중 532 변경)**: Bodyweight 373 / Barbell 154 / NULL 5 / EZ Bar 유지 21. STEP B(보수적) 덤벨·EZ 명시 8건 백필. garbage 허브 default_for: Assisted 376→0, EZ 177→21.

**검증 4단계 (전부 통과)**:
1. prod 실데이터 결정론 시뮬 — 532 변경 분포 확인
2. SQL 정규식 ↔ 검증 분류기 미러 대조 — **불일치 0**
3. **codex 리뷰** `SHIP-WITH-FIXES` 2건 반영: (a) 어시스트-머신 방어가드(`assisted` & !self/band → 머신 유지; prod 매칭 0이나 포터빌리티), (b) garbage hub 룩업 술어 강화(EZ `bar_weight=10`, Assisted `equipment_type='bodyweight'`)
4. **실 Postgres(docker) E2E** — 20분기 픽스처 20/20 정확 + 멱등 재실행 무변화 + canon누락 RAISE 롤백

**후속(별도 PR, 본 마이그 범위 밖)**: 중복 dumbbell(`6eff9e86`) dedup · Olympic Barbell dedup · Smith 타입오류(barbell→machine) — DELETE/ALTER라 백업+허가 필요. 맨몸-NULL ~55개 백필은 모호성으로 보류.

**배포**: PR → develop → main → ECS `alembic upgrade head` → prod hnwegx 반영. (admin.py WorkoutX import 의 백필 로직도 동일 tie-break 결함이 있으니 향후 재import 시 재발 방지 위해 별도 수정 권고.)
