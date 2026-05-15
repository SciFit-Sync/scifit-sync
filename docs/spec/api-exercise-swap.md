# 🔄 운동 변경 선택 (루틴 종목 교체)

## 📌 개요

루틴 상세 페이지에서 특정 운동을 다른 운동으로 교체하거나, 세트/반복/중량 등 세부 정보를 부분 수정합니다. "운동 변경 조회" 결과에서 선택한 운동을 이 엔드포인트로 적용합니다.

**Endpoint**

```
PATCH /api/v1/routines/{routineId}/exercises/{routineExerciseId}
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
| routineId | String (UUID) | ✅ | 본인 소유 루틴 ID (soft delete 제외) |
| routineExerciseId | String (UUID) | ✅ | `routine_exercises.id` (루틴 내 운동 인스턴스 ID) |

**Body** — 보낸 필드만 부분 업데이트 (PATCH semantics)

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| exerciseId | String (UUID) | ❌ | **종목 자체 교체** 시 새 운동 ID. 없으면 기존 유지 |
| equipmentId | String (UUID) | ❌ | 사용 기구 변경. 사용자 헬스장 보유 검증 |
| sets | Integer | ❌ | 세트 수 (≥ 1) |
| repsMin | Integer | ❌ | 최소 반복 (≥ 1, ≤ repsMax) |
| repsMax | Integer | ❌ | 최대 반복 (≥ 1) |
| weightKg | Float | ❌ | 표시 중량 (도르래 보정 전, ≥ 0). 누락 시 1RM × 목표비율로 자동 계산 |
| restSeconds | Integer | ❌ | 휴식 시간 (초, ≥ 0) |
| note | String | ❌ | 메모 (≤ 500자) |

**Example**

```json
{
  "exerciseId": "550e8400-e29b-41d4-a716-446655440100",
  "equipmentId": "550e8400-e29b-41d4-a716-446655440200",
  "sets": 4,
  "repsMin": 8,
  "repsMax": 12,
  "weightKg": 22.5,
  "restSeconds": 90,
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
    "routineExerciseId": "550e8400-e29b-41d4-a716-446655440300",
    "exerciseId": "550e8400-e29b-41d4-a716-446655440100",
    "exerciseName": "인클라인 덤벨 프레스",
    "equipmentId": "550e8400-e29b-41d4-a716-446655440200",
    "equipmentName": "PowerBlock Pro 90",
    "orderIndex": 0,
    "sets": 4,
    "repsMin": 8,
    "repsMax": 12,
    "weightKg": 22.5,
    "restSeconds": 90,
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
    "message": "repsMin은 repsMax보다 작거나 같아야 합니다.",
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
