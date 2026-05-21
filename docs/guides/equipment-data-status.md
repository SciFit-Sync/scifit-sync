# 기구 데이터 작업 현황

> 작성일: 2026-05-20  
> 작성자: namgw

---

## 완료 작업

### 1. ERD 설계 검토 및 문서화

| 문서 | 상태 | 비고 |
|------|------|------|
| `docs/spec/2026-05-19-erd-v2.2-stack-jsonb-check.md` | ✅ 검토 완료 | 파일명 `(1)` suffix 제거 |
| `docs/spec/database-schema.md` | ✅ v2.2 반영 완료 | 4곳 업데이트 |

`database-schema.md` 업데이트 내용:
- CHECK 블록에 `chk_stack_weight_shape` 추가 (v2.2)
- `stack_weight` JSONB 단락 → "DB CHECK 책임 / 앱 레이어 책임" 2단 구조로 재구성
- mermaid `stack_unit` 설명에 "3필드 단위 동일 강제" 명시
- 변경 이력 표에 v2.2 row 추가

### 2. 기구 데이터 수집

| 파일 | 브랜드 | 행 수 |
|------|--------|-------|
| `mlops/data/hammer_strength_equipments.csv` | Hammer Strength | 39행 |
| `mlops/data/newtech_equipments.csv` | Newtech | 29행 |
| `mlops/data/panatta_equipments.csv` | Panatta | 33행 |

특이사항:
- Hammer Strength: 제품군에 따라 단위 혼재 (plate-loaded = kg, selectorized = lb)
- Hammer Strength Select 시리즈 변동 스택 패턴 (`"10lb*5, 15lb*10"` 형식) 6건 → import 시 JSONB `{"pattern": [...]}` 변환
- `"?"` 값 0건 — 전부 수정 완료 (2026-05-20)
- Hammer Strength: T-Bar Row bar_weight/min_stack/max_stack/stack_weight 채워짐
- Newtech: 빈 행 2개 제거, GHD 90° Roman Chair 신규 추가, 수치값 단위 전부 명시, Preacher Curl bar_weight(7.5kg) 채워짐, `sub_category` `"lower back"` → `"lower_back"` 수정
- Panatta: Preacher curl bench bar_weight(10kg) 채워짐

### 3. Alembic 008 마이그레이션 작성

**파일**: `server/alembic/versions/008_equipment_schema_v2.py`

upgrade 내용:
- `equipment_brands`: `default_bar_unit`, `default_stack_unit` 컬럼 추가 (NOT NULL DEFAULT 'kg')
- `equipments`: `name_en`, `sub_category`, `bar_weight_unit`, `stack_unit` 컬럼 추가
- 컬럼 RENAME: `bar_weight_kg→bar_weight`, `min_stack_kg→min_stack`, `max_stack_kg→max_stack`
- `stack_weight_kg` RENAME + `float → JSONB` 타입 변환 (기존 float 값 → `{"value": N}` 자동 변환)
- CHECK 제약 3개 추가: `chk_bar_unit_synced`, `chk_stack_unit_synced`, `chk_stack_weight_shape`

downgrade: 역순 복원 (pattern JSONB → NULL 처리)

### 4. SQLAlchemy 모델 업데이트

**파일**: `server/app/models/gym.py`

- `WeightUnit` StrEnum 추가 (`kg` | `lb`)
- `EquipmentBrand`: `default_bar_unit`, `default_stack_unit` 컬럼 추가
- `Equipment`: 컬럼명 `_kg` suffix 제거, `stack_weight: dict[str, Any] | None (JSONB)`, `bar_weight_unit`, `stack_unit`, `sub_category` 추가

**파일**: `server/app/models/__init__.py`

- `WeightUnit` export 추가

### 5. CSV Import 스크립트 작성

**파일**: `server/import_equipment_csv.py`

기능:
- CSV 값에서 단위 파싱: `"5kg"` → (5.0, 'kg'), `"10lb"` → (10.0, 'lb')
- 단위 없는 값 (`"120"`) → 브랜드 `default_stack_unit` fallback
- 변동 패턴 변환: `"10lb*5, 15lb*10"` → `{"pattern": [{"from":1,"to":5,"value":10}, {"from":6,"to":15,"value":15}]}`
- `"?"`, 빈 값 → NULL
- `equipment_type` 없는 행 → skip (NOT NULL)
- Idempotent: (brand_id, name) 중복 시 skip
- `--dry-run` 옵션 지원

---

## 남은 작업

### DB 서버 연결 후 실행 (Supabase `DATABASE_URL` 필요)

```bash
# server/ 디렉토리에서

# Step 1: 마이그레이션 적용
alembic upgrade 008

# Step 2: 파싱 결과 확인 (DB 변경 없음)
python import_equipment_csv.py --dry-run

# Step 3: 실제 import
python import_equipment_csv.py
```

예상 결과: 브랜드 3개 생성, 기구 약 100건 삽입 (equipment_type 없는 행 제외)

---

## 관련 파일 위치

| 파일 | 경로 |
|------|------|
| ERD v2.2 spec | `docs/spec/2026-05-19-erd-v2.2-stack-jsonb-check.md` |
| DB 스키마 문서 | `docs/spec/database-schema.md` |
| 기구 CSV (3개) | `mlops/data/*_equipments.csv` |
| Alembic 008 | `server/alembic/versions/008_equipment_schema_v2.py` |
| SQLAlchemy 모델 | `server/app/models/gym.py` |
| CSV import 스크립트 | `server/import_equipment_csv.py` |
