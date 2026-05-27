# Handoff — 찬스짐 기구 데이터 seed

> 작성일: 2026-05-27
> 브랜치: `feat/namgw/chat-doi-goldset-check`

---

## 1. 완료된 작업

### 1.1 데이터 파일
- `mlops/data/chancegym_equipments.csv` 신규 작성 (33개 기구)
  - 브랜드: GYM80, Newtech, Lexco, Lexco MasterPro→Lexco, Booty Builder, Salus
  - 제조사 없는 범용 기구 3개: Barbell, Dumbbell, Smith machine (brand_id·category·sub_category 모두 NULL)
- `mlops/data/equipments_seed.csv` 에 찬스짐 기구 33개 append
  - 전체 행 `name_en` 공백 → name 값으로 채움

### 1.2 마이그레이션 파일
- `server/alembic/versions/20260524_seed_ai_gym_equipments.py`
  - Lexco MasterPro 브랜드 제거 (브랜드 6→5개)
  - Lexco MasterPro brand_id를 참조하던 기구 5개를 Lexco brand_id로 교체

### 1.3 브랜드 결정사항
| 브랜드 | brand_id |
|--------|----------|
| GYM80 | `ae5eaca3-7a8c-5957-99db-a902ba8acc5b` |
| Newtech | `1decce92-8e90-5ce9-94c4-d66989a4981d` |
| Lexco (MasterPro 포함 통일) | `d151cfa6-307d-5fff-acb4-8223c8db85d9` |
| Booty Builder | `c0802a7e-b07a-5bcb-826a-ef45a8188a7c` |
| Salus | `6dc8a99d-5fe9-5736-9704-e8820d9805b3` |

---

## 2. 다음 단계 (이어서 진행할 작업)

### 우선순위 1: 찬스짐 기구 seed 마이그레이션 파일 작성
`equipments_seed.csv`는 `20260521_seed_equipments` 마이그레이션이 최초 1회만 읽으므로, prod DB에 이미 적용된 상태에서는 CSV에 추가한 33개가 자동으로 들어가지 않는다. 새 마이그레이션 파일이 필요하다.

```
server/alembic/versions/20260527_seed_chancegym_equipments.py
```

- `down_revision = "20260524_seed_ai_gym_equipments"`
- 기존 `20260524` 패턴 동일하게 작성 (`_EQUIPMENTS` 리스트 + ON CONFLICT DO NOTHING)
- chancegym_equipments.csv의 33개 행을 Python 리스트로 변환해서 삽입
- Barbell/Dumbbell/Smith machine의 brand_id는 NULL

### 우선순위 2: 찬스짐 gym 등록 및 gym_equipments 매핑
- `gyms` 테이블에 찬스짐 등록 (별도 seed 또는 앱 온보딩 플로우)
- `gym_equipments` 테이블에 찬스짐 gym_id + 위 33개 equipment_id 매핑

### 우선순위 3: Barbell/Dumbbell/Smith machine 중량 계산 동작 확인
- brand_id·category·sub_category가 NULL인 상태에서 `load_calc.calculate_effective_weight`가 `equipment_type` 분기로 정상 동작하는지 확인
- Barbell: `bar_weight=20kg`, Smith machine: `bar_weight=15kg` 반영 여부 확인

---

## 3. 파일 위치 요약

| 파일 | 설명 |
|------|------|
| `mlops/data/chancegym_equipments.csv` | 찬스짐 원본 데이터 (참고용) |
| `mlops/data/equipments_seed.csv` | 전체 기구 seed CSV (찬스짐 포함) |
| `server/alembic/versions/20260524_seed_ai_gym_equipments.py` | AI팀 기구 seed (Lexco 통일 반영) |
| `server/alembic/versions/20260521_seed_equipments.py` | CSV → DB 적재 마이그레이션 |
