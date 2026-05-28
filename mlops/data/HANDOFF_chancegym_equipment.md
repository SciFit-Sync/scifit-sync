# Handoff — 찬스짐 기구 데이터 seed

> 최종 업데이트: 2026-05-28
> 브랜치: `feat/namgw/chancegym-equipment-seed` → 후속 PR `feat/sungjoon/chancegym-gym-seed`

---

## 1. 완료된 작업

### 1.1 커밋 이력

| 커밋 | 내용 |
|------|------|
| `956629a` | Lexco MasterPro 브랜드를 Lexco로 통일 (마이그레이션 파일) |
| `bf0aa4b` | 찬스짐 기구 데이터 추가 및 equipments_seed 정비 |
| `15481e2` | 핸드오프 문서 작성 |

### 1.2 데이터 파일

**`mlops/data/chancegym_equipments.csv`** (신규, 참고용 원본)
- 찬스짐에 있는 기구 33개 정리
- 브랜드: GYM80, Newtech, Lexco, Booty Builder, Salus
- 범용 기구 3개 (Barbell, Dumbbell, Smith machine) — brand_id · category · sub_category 모두 NULL

**`mlops/data/equipments_seed.csv`** (수정)
- 찬스짐 기구 33개 append (row 103~135)
- 기존 전체 행 `name_en` 빈값 → name 값으로 채움
- Lexco MasterPro brand_id → Lexco brand_id로 전체 교체

### 1.3 마이그레이션 파일

**`server/alembic/versions/20260524_seed_ai_gym_equipments.py`** (수정)
- `_BRANDS`에서 Lexco MasterPro 항목 제거 (6→5개)
- Lexco MasterPro brand_id(`df8ceb47...`)를 참조하던 기구 5개를 Lexco brand_id(`d151cfa6...`)로 교체
  - Hack Slide, Plate Loaded Seated Row, Plate Loaded Shoulder Press, Plate Loaded Pulldown, Seated Row

### 1.4 브랜드 결정사항

Lexco MasterPro는 Lexco와 동일 제조사이므로 단일 브랜드로 통일했다. 이후 기구 데이터 추가 시 Lexco MasterPro는 사용하지 않는다.

| 브랜드 | brand_id |
|--------|----------|
| Hammer Strength | `5a83446f-440a-5e5a-8071-f62e6244cbe6` |
| Newtech | `1decce92-8e90-5ce9-94c4-d66989a4981d` |
| Panatta | `2eec52b6-35a4-57ee-8591-72283071f9e3` |
| GYM80 | `ae5eaca3-7a8c-5957-99db-a902ba8acc5b` |
| NEM | `00450d91-d251-5353-a003-0e1ca6adcc43` |
| Booty Builder | `c0802a7e-b07a-5bcb-826a-ef45a8188a7c` |
| Salus | `6dc8a99d-5fe9-5736-9704-e8820d9805b3` |
| **Lexco** (MasterPro 포함 통일) | `d151cfa6-307d-5fff-acb4-8223c8db85d9` |

---

## 2. 다음 단계

### ✅ 우선순위 1: 찬스짐 기구 seed 마이그레이션 — 완료 (2026-05-27)

`server/alembic/versions/20260527_seed_chancegym_equipments.py` 작성 완료. 33개 기구 prod 적재용 INSERT, `ON CONFLICT DO NOTHING` 멱등 처리, `uuid5(NAMESPACE_DNS, "scifit-chancegym-{name}-{brand}")` 결정론적 UUID. 후속 `20260528_fix_pulley_ratio`에서 pulley_ratio 2→0.5 보정도 적용됨.

### ✅ 우선순위 2: 찬스짐 gym 등록 및 gym_equipments 매핑 — 완료 (2026-05-28)

`server/alembic/versions/20260528_seed_chancegym_gym.py` 작성 완료.
- `gyms`: '더찬스짐' 1행 — `id=ecdd073b-f894-5c5a-86cc-a9b42a4e6985` (uuid5(NAMESPACE_DNS, "scifit-gym-kakao-1875030524")), kakao_place_id=`1875030524`, address='경기 용인시 처인구 모현읍 외대로26번길 25-1', lat=37.3336260282492, lng=127.25172831281385
- `gym_equipments`: 33개 매핑 (quantity=1) — 20260527에서 적재한 equipment_id 33개를 그대로 참조
- 멱등성: 두 INSERT 모두 `ON CONFLICT DO NOTHING`, downgrade는 gym_equipments → gyms 순 DELETE
- down_revision: `20260528_fix_pulley_ratio`

### ✅ 우선순위 3: 범용 기구 중량 계산 동작 확인 — 검증 완료 (2026-05-28)

`server/app/services/load_calc.py`의 `calculate_effective_weight`는 이미 `equipment_type` 단일 매개변수로만 분기하며 `category` / `sub_category`를 절대 참조하지 않는다. 따라서 범용 기구의 NULL category는 무영향.

`server/tests/test_load_calc.py`가 5개 equipment_type 분기를 모두 커버 (13개 케이스):
- `test_barbell` — `bar_weight=20, added=60` → `80kg` ✅
- `test_dumbbell` — `added=20` → `20kg` ✅
- Smith machine은 `equipment_type='barbell'`로 등록되어 barbell 분기 사용 ✅

추가 테스트 작성 불필요.

---

## 3. 파일 위치 요약

| 파일 | 설명 |
|------|------|
| `mlops/data/chancegym_equipments.csv` | 찬스짐 기구 원본 (참고용) |
| `mlops/data/equipments_seed.csv` | 전체 기구 seed CSV (찬스짐 33개 포함) |
| `server/alembic/versions/20260521_seed_equipments.py` | CSV → DB 적재 마이그레이션 (최초 1회) |
| `server/alembic/versions/20260524_seed_ai_gym_equipments.py` | AI팀 기구 seed, Lexco 통일 반영 |
| `server/alembic/versions/20260527_seed_chancegym_equipments.py` | ✅ 찬스짐 기구 33개 prod 적재 |
| `server/alembic/versions/20260528_fix_pulley_ratio.py` | ✅ pulley_ratio 2→0.5 보정 |
| `server/alembic/versions/20260528_seed_chancegym_gym.py` | ✅ 더찬스짐 gym 등록 + gym_equipments 33개 매핑 |
