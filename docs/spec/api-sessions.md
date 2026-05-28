# 세션(운동 로그) API 명세

> 스펙 기준: 실제 백엔드 구현 (`server/app/api/v1/sessions.py`)
> 모든 필드명은 **snake_case** (D-15)

## POST /api/v1/sessions — 운동 시작

**Request Body**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| routine_id | UUID | ❌ | 시작할 루틴 ID. 지정 시 첫 번째 day 자동 선택 |
| routine_day_id | UUID | ❌ | 특정 분할 day ID. routine_id 없이도 사용 가능 |
| gym_id | UUID | ❌ | 헬스장 ID. 미지정 시 루틴의 gym_id 자동 복사 |

**Response (201)**

```json
{
  "success": true,
  "data": {
    "session_id": "uuid",
    "routine_id": "uuid",
    "routine_name": "상체 근비대 루틴",
    "gym_id": "uuid",
    "started_at": "2026-05-28T10:00:00",
    "message": "운동을 시작합니다!"
  }
}
```

---

## POST /api/v1/sessions/{session_id}/sets — 세트 기록

**Request Body**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| exercise_id | UUID | ✅ | 종목 ID |
| routine_exercise_id | UUID | ❌ | 루틴 운동 ID (있으면 연결) |
| set_number | Integer | ✅ | 세트 번호 (1 이상) |
| weight_kg | Float | ❌ | 중량 (kg) |
| reps | Integer | ✅ | 횟수 (0 이상) |
| rpe | Float | ❌ | RPE (1.0~10.0) |
| is_completed | Boolean | ❌ | 완료 여부 (기본값 true) |

**Response (201)**

```json
{
  "success": true,
  "data": {
    "set_id": "uuid",
    "exercise_id": "uuid",
    "exercise_name": "인클라인 덤벨 프레스",
    "set_number": 1,
    "weight_kg": 22.5,
    "reps": 10,
    "rpe": 7.0,
    "is_completed": true,
    "performed_at": "2026-05-28T10:05:00"
  }
}
```

---

## PATCH /api/v1/sessions/{session_id}/finish — 운동 완료

**Request Body**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| finished_at | DateTime | ❌ | 종료 시각. 미지정 시 서버 현재 시각 |

**Response (200)**

```json
{
  "success": true,
  "data": {
    "session_id": "uuid",
    "routine_day_id": "uuid",
    "gym_id": "uuid",
    "started_at": "2026-05-28T10:00:00",
    "finished_at": "2026-05-28T11:15:00",
    "status": "completed",
    "routine_name": "상체 근비대 루틴",
    "duration_minutes": 75,
    "total_sets": 16,
    "completed_exercises": 4,
    "total_calories": 291
  }
}
```

> `total_calories` = MET 5.0 × 체중(kg) × 운동시간(h). 체중 기록 없으면 70kg 기준.

---

## GET /api/v1/sessions/{session_id}/rest-timer — 휴식 타이머

**Query Parameters**

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| routine_exercise_id | UUID | ❌ | 루틴 운동 ID. 있으면 루틴에 설정된 rest_seconds 사용 |
| goal | String | ❌ | hypertrophy / strength / endurance / rehabilitation. routine_exercise_id 없을 때 사용 |

**Response (200)**

```json
{
  "success": true,
  "data": {
    "rest_seconds": 90,
    "min_rest_seconds": 60,
    "max_rest_seconds": 120,
    "message": "권장 휴식: 1분~2분",
    "based_on": "goal_default"
  }
}
```

| based_on | 의미 |
|---|---|
| routine | routine_exercise_id로 조회한 루틴 설정값 기준 |
| goal_default | goal 파라미터 기반 기본값 |

**goal별 기본값**

| goal | rest_seconds | min | max |
|---|---|---|---|
| hypertrophy | 90 | 60 | 120 |
| strength | 180 | 120 | 300 |
| endurance | 60 | 30 | 60 |
| rehabilitation | 60 | 30 | 90 |
