# 🔄 운동 변경 선택 (루틴 종목 교체)

## 📌 개요

루틴 상세 페이지에서 특정 운동을 다른 운동으로 교체하거나, 세트/반복/중량 등 세부 정보를 부분 수정합니다. "운동 변경 조회" 결과에서 선택한 운동을 이 엔드포인트로 적용합니다.

**Endpoint**

```
PATCH /api/v1/routines/{routine_id}/exercises/{routine_exercise_id}
```

> ⚠️ Notion에 적힌 `POST /api/v1/exercises` 는 실제 구현과 다릅니다. 위 PATCH 가 정본.

---

## ✅ Request

**Headers**

```
Authorization: Bearer {accessToken}
Content-Type: application/json
```

**Path Parameters**

| 파라미터 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| routine_id | String (UUID) | ✅ | 본인 소유 루틴 ID (soft delete 제외) |
| routine_exercise_id | String (UUID) | ✅ | `routine_exercises.id` (루틴 내 운동 인스턴스 ID) |

**Body** — 보낸 필드만 부분 업데이트 (PATCH semantics)

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| exercise_id | String (UUID) | ❌ | **종목 자체 교체** 시 새 운동 ID. 없으면 기존 유지 |
| equipment_id | String (UUID) | ❌ | 사용 기구 변경. 사용자 헬스장 보유 검증 |

> **PR-4 동작 (equipment_id NOT NULL):** `routine_exercises.equipment_id`는 NOT NULL이므로 운동마다 항상 기구가 묶인다.
> `exercise_id`만 보내 종목을 교체하면 서버가 그 운동에 쓸 기구를 **결정론적으로 자동 선택**한다(우선순위: 루틴 헬스장 머신 → 전 헬스장 공통 프리웨이트). `equipment_id`를 함께 보내면 그 값이 우선한다.
> 종목 교체 시 헬스장에서 쓸 수 있는 기구가 하나도 없으면 **409 CONFLICT** (`교체할 운동에 사용할 수 있는 기구가 헬스장에 없습니다.`).
| sets | Integer | ❌ | 세트 수 (≥ 1) |
| reps_min | Integer | ❌ | 최소 반복 (≥ 1, ≤ reps_max) |
| reps_max | Integer | ❌ | 최대 반복 (≥ 1) |
| weight_kg | Float | ❌ | 표시 중량 (도르래 보정 전, ≥ 0). 누락 시 1RM × 목표비율로 자동 계산 |
| rest_seconds | Integer | ❌ | 휴식 시간 (초, ≥ 0) |
| note | String | ❌ | 메모 (≤ 500자) |

**Example**

```json
{
  "exercise_id": "550e8400-e29b-41d4-a716-446655440100",
  "equipment_id": "550e8400-e29b-41d4-a716-446655440200",
  "sets": 4,
  "reps_min": 8,
  "reps_max": 12,
  "weight_kg": 22.5,
  "rest_seconds": 90,
  "note": "어깨 통증으로 인클라인 덤벨로 교체"
}
```

---

## ✅ Response

**Success (200)**

```json
{
  "success": true,
  "data": {
    "routine_exercise_id": "550e8400-e29b-41d4-a716-446655440300",
    "exercise_id": "550e8400-e29b-41d4-a716-446655440100",
    "exercise_name": "인클라인 덤벨 프레스",
    "equipment_id": "550e8400-e29b-41d4-a716-446655440200",
    "equipment_name": "PowerBlock Pro 90",
    "order_index": 0,
    "sets": 4,
    "reps_min": 8,
    "reps_max": 12,
    "weight_kg": 22.5,
    "rest_seconds": 90,
    "note": "어깨 통증으로 인클라인 덤벨로 교체"
  }
}
```

**Error (400)**

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "reps_min은 reps_max보다 작거나 같아야 합니다.",
    "request_id": "req_abc123"
  }
}
```

**Error (401)**

```json
{
  "success": false,
  "error": {
    "code": "UNAUTHORIZED",
    "message": "인증이 필요합니다.",
    "request_id": "req_abc123"
  }
}
```

**Error (403)**

```json
{
  "success": false,
  "error": {
    "code": "FORBIDDEN",
    "message": "해당 루틴에 접근 권한이 없습니다.",
    "request_id": "req_abc123"
  }
}
```

**Error (404)**

```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "루틴 또는 운동을 찾을 수 없습니다.",
    "request_id": "req_abc123"
  }
}
```

**Error (409)**

```json
{
  "success": false,
  "error": {
    "code": "CONFLICT",
    "message": "선택한 기구가 헬스장에 등록되어 있지 않습니다.",
    "request_id": "req_abc123"
  }
}
```
