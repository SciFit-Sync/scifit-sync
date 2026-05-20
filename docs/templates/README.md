# 기구 데이터 추가용 CSV 템플릿

> 새 브랜드 카탈로그를 추가할 때 사용하는 표준 CSV 형식 안내.
> 스키마 정의: `docs/spec/database-schema.md` (v2.1)

---

## 1. 파일 명명 규칙

```
<brand_slug>_equipments.csv
```

예시:
- `hammer_strength_equipments.csv`
- `newtech_equipments.csv`
- `panatta_equipments.csv`

`<brand_slug>`은 소문자·언더스코어로 표기하며, ETL이 파일명을 `equipment_brands.name`과 매핑한다. 매핑 테이블은 ETL 스크립트(`server/scripts/import_equipment_csv.py`, Phase 2+ #2 브랜치)에 정의된다.

> **저장 위치**: 실제 수집된 CSV는 git 외부 `data/` 디렉토리에 둔다(`capstone/data/<brand_slug>_equipments.csv`). 본 디렉토리(`docs/templates/`)는 형식 정의 전용.

---

## 2. 인코딩

**UTF-8 (BOM 없음) 권장.**

기존 수집 파일 중 `newtech_equipments.csv`, `panatta_equipments.csv`는 **CP949** 인코딩이라 import 시 별도 변환 필요. 신규 파일은 UTF-8로 작성한다.

---

## 3. 컬럼 정의 (13개)

| # | 컬럼 | CSV 표기 | 비어있을 때 | DB 적재 시 처리 (Phase 2+ ETL) |
|---|---|---|---|---|
| 1 | `id` | (빈 값) | 항상 비움 | DB가 `gen_random_uuid()` 자동 생성 |
| 2 | `brand_id` | (빈 값) | 항상 비움 | 파일명 → `equipment_brands.name` → UUID 조회 |
| 3 | `name` | 영문/한글 | 필수 | 그대로 |
| 4 | `category` | enum 6종 | 필수 | enum 검증 (`chest\|back\|shoulders\|arms\|core\|legs`) |
| 5 | `sub_category` | snake_case | 권장 | 공백 → 밑줄 정규화 (예: `lower back` → `lower_back`) |
| 6 | `equipment_type` | enum 5종 | 필수 | enum 검증 (`cable\|machine\|barbell\|dumbbell\|bodyweight`) |
| 7 | `pulley_ratio` | 정수/소수/`null` | 허용 | `null` 문자열 → SQL NULL, 숫자는 float |
| 8 | `bar_weight_kg` | `<n>kg` / `<n>lb` / `null` | 허용 | 단위 추출 → DB의 `bar_weight` + `bar_weight_unit` |
| 9 | `min_stack_kg` | `<n>kg` / `<n>lb` / `null` | 허용 | 단위 추출 → DB의 `min_stack` |
| 10 | `max_stack_kg` | `<n>kg` / `<n>lb` / `null` | 허용 | 단위 추출 → DB의 `max_stack` |
| 11 | `stack_weight_kg` | `<n>kg` / `<n>lb` / 변동형 / `null` | 허용 | 파싱 → DB의 `stack_weight`(JSONB) + `stack_unit` |
| 12 | `image_url` | URL | 허용 | 그대로 |
| 13 | `updated_at` | (빈 값) | 항상 비움 | DB가 `now()` 자동 |

> CSV 컬럼명에 `_kg` 접미사가 남아 있는 것은 기존 수집 파일과의 호환을 위함이다. DB 컬럼은 v2.1에서 `bar_weight`, `min_stack`, `max_stack`, `stack_weight`로 RENAME되며 ETL이 import 시 매핑한다.

---

## 4. 무게 컬럼 값 형식 (중요)

`bar_weight_kg`, `min_stack_kg`, `max_stack_kg`, `stack_weight_kg` 4개 컬럼은 다음 4가지 형식을 허용한다:

### 4-1. 단위 포함 단일값

```
5kg          → DB: value=5, unit='kg'
10lb         → DB: value=10, unit='lb'
2.5kg        → DB: value=2.5, unit='kg'
```

### 4-2. `null` 문자열

```
null         → DB: NULL
```

문자 `null` (소문자) 사용. 빈 셀(`,,`)도 NULL로 해석되나, 일관성을 위해 명시적 `null` 권장.

### 4-3. 단위 없는 숫자 (pulley_ratio 전용)

```
1            → DB: 1.0
2            → DB: 2.0
1.5          → DB: 1.5
```

`pulley_ratio`만 단위 없는 raw decimal 허용. 다른 무게 컬럼은 반드시 단위 포함.

### 4-4. 변동형 스택 패턴 (stack_weight_kg 전용)

블록 번호에 따라 스택 무게가 달라지는 경우 (예: Hammer Strength Select 시리즈):

```
10lb*5, 15lb*10
```

해석: 1~5번 블록은 각 10lb, 6~15번 블록은 각 15lb. DB의 `stack_weight` JSONB로 저장:

```json
{
  "pattern": [
    { "from": 1,  "to": 5,  "value": 10 },
    { "from": 6,  "to": 15, "value": 15 }
  ]
}
```

(단위는 같은 행의 `stack_unit`이 결정 — 위 예시는 `'lb'`.)

---

## 5. 같은 행에 lb/kg 혼재 허용

`bar`와 `stack`은 서로 다른 단위를 가질 수 있다. 같은 행에 다음 조합이 정상이다:

```csv
,,Iso-Lateral Wide Pulldown,back,upper_back,machine,null,2lb,0kg,120kg,5kg,...
```

- `bar_weight_kg=2lb` — 제조사가 표기한 레버 무게 (미국 브랜드, lb)
- `min_stack_kg=0kg, max_stack_kg=120kg, stack_weight_kg=5kg` — 사용자가 끼우는 원판 (국내 헬스장 표준 kg)

ETL은 두 그룹을 독립적으로 단위 감지·검증한다.

---

## 6. 데이터 품질 체크리스트

CSV 작성 후 다음을 확인:

- [ ] 모든 행에 `name`, `category`, `equipment_type` 채워짐
- [ ] `category` 값이 enum 6종 중 하나 (`chest|back|shoulders|arms|core|legs`)
- [ ] `equipment_type` 값이 enum 5종 중 하나 (`cable|machine|barbell|dumbbell|bodyweight`)
- [ ] `sub_category`는 snake_case (공백 대신 밑줄, 예: `lower_back`)
- [ ] 무게 값에 단위 접미사 누락 없음 (`5` → `5kg` 또는 `5lb`로 명시)
- [ ] `null`은 소문자, 빈 셀과 혼용 시 의미 동일하지만 가급적 일관 사용
- [ ] 같은 그룹(`bar` 또는 `stack`) 내 단위 일관 (예: `min_stack=10lb`와 `max_stack=120kg` 혼합 금지)
- [ ] `image_url`이 https URL이거나 비어있음

---

## 7. 예시 행 (참고용)

다음은 다양한 시나리오의 예시. **실제 템플릿(`equipment_template.csv`)에는 헤더만 두고, 작성 시 아래 패턴을 참고하여 입력한다.**

```csv
id,brand_id,name,category,sub_category,equipment_type,pulley_ratio,bar_weight_kg,min_stack_kg,max_stack_kg,stack_weight_kg,image_url,updated_at
# (1) 한국 브랜드 plate-loaded — 전부 kg
,,Lat Pulldown,back,upper_back,machine,1,null,5kg,100kg,5kg,https://example.com/img1.jpg,
# (2) 미국 selectorized — 전부 lb
,,MTS Iso-Lateral Row,back,lower_back,machine,1,null,10lb,150lb,10lb,https://example.com/img2.jpg,
# (3) 변동형 스택 — Hammer Strength Select
,,HS Select Pulldown,back,upper_back,machine,1,null,10lb,200lb,"10lb*5, 15lb*10",https://example.com/img3.jpg,
# (4) 바=lb, 스택=kg 혼재 (plate-loaded, 미국 제조)
,,Iso-Lateral Wide Pulldown,back,upper_back,machine,null,2lb,0kg,120kg,5kg,https://example.com/img4.jpg,
# (5) 바벨 — 스택 없음
,,Olympic Barbell,legs,quads,barbell,1,20kg,null,null,null,,
# (6) 케이블 도르래 비율 2
,,Advance Lat Pulldown,back,upper_back,machine,2,null,5kg,125kg,5kg,https://example.com/img6.jpg,
```

위 행을 CSV에 그대로 붙여넣지 말 것 — `#`은 주석 표시일 뿐 CSV 표준이 아니다. 실제 데이터에는 주석 라인 없이 데이터 행만 둔다.

---

## 8. ETL 가져오기 (Phase 2+, 참고)

본 템플릿으로 작성된 파일은 후속 Phase 2 브랜치에서 `server/scripts/import_equipment_csv.py`가 처리한다:

1. 파일명에서 brand 추출 → `equipment_brands.id` 조회
2. 인코딩 자동 감지 (UTF-8 → CP949 fallback)
3. 각 행 파싱: 단위 추출, `null` 변환, 변동형 패턴 JSONB 변환
4. CHECK 제약(`chk_bar_unit_synced`, `chk_stack_unit_synced`) 사전 검증
5. `equipments` 테이블에 idempotent upsert (name + brand_id 키로)
6. 실패 행은 리포트로 출력 후 건너뜀

상세 구현은 후속 브랜치 PR을 참조한다.
