# Handoff — 찬스짐 기구 데이터 seed

> 최종 업데이트: 2026-05-27
> 브랜치: `feat/namgw/chancegym-equipment-seed`

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

### 우선순위 1: 찬스짐 기구 seed 마이그레이션 파일 작성 (**필수**)

`equipments_seed.csv`는 `20260521_seed_equipments` 마이그레이션이 최초 1회만 읽는다. prod DB에 이미 적용된 상태이므로 CSV 추가분(33개)은 자동으로 반영되지 않는다. 별도 마이그레이션이 필요하다.

작성할 파일:
```
server/alembic/versions/20260527_seed_chancegym_equipments.py
```

작성 기준:
- `down_revision = "20260524_seed_ai_gym_equipments"`
- `20260524` 패턴 동일하게 작성 (`_EQUIPMENTS` Python 리스트 + `ON CONFLICT DO NOTHING`)
- `chancegym_equipments.csv`의 33개 행을 Python 리스트로 변환
- Barbell / Dumbbell / Smith machine의 `brand_id = None`
- 찬스짐에서 쓰는 브랜드(GYM80, Newtech, Lexco, Booty Builder, Salus)는 이미 이전 마이그레이션에서 등록됐으므로 `_BRANDS` 삽입 불필요

각 기구의 UUID는 결정론적으로 생성:
```python
import uuid
uuid.uuid5(uuid.NAMESPACE_DNS, f"scifit-chancegym-{name}-{brand}")
```
→ `mlops/data/chancegym_equipments.csv` 행 순서별로 이미 생성된 UUID는 `equipments_seed.csv` 103번 줄 이후에서 확인 가능

### 우선순위 2: 찬스짐 gym 등록 및 gym_equipments 매핑

- `gyms` 테이블에 찬스짐 등록 (앱 온보딩 플로우 또는 별도 seed)
- `gym_equipments` 테이블에 `gym_id` + 위 33개 `equipment_id` + `quantity` 매핑

### 우선순위 3: 범용 기구 중량 계산 동작 확인

Barbell / Dumbbell / Smith machine은 brand_id · category · sub_category가 NULL이다. `load_calc.calculate_effective_weight`가 `equipment_type` 분기로만 동작하는지 확인 필요.

```python
# 확인 포인트: server/app/services/load_calc.py
# barbell: bar_weight=20kg, pulley_ratio=1.0 → effective = bar_weight + added_weight
# dumbbell: equipment.bar_weight 없음 → effective = added_weight
# Smith machine: bar_weight=15kg → effective = bar_weight + added_weight
```

---

## 3. 파일 위치 요약

| 파일 | 설명 |
|------|------|
| `mlops/data/chancegym_equipments.csv` | 찬스짐 기구 원본 (참고용) |
| `mlops/data/equipments_seed.csv` | 전체 기구 seed CSV (찬스짐 33개 포함) |
| `server/alembic/versions/20260521_seed_equipments.py` | CSV → DB 적재 마이그레이션 (최초 1회) |
| `server/alembic/versions/20260524_seed_ai_gym_equipments.py` | AI팀 기구 seed, Lexco 통일 반영 |
| `server/alembic/versions/20260527_seed_chancegym_equipments.py` | **작성 필요** — 찬스짐 기구 prod 적재 |
