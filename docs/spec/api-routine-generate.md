# 🤖 AI 루틴 생성

## 📌 개요

목표, 부위, 세션 시간, 부상 정보를 기반으로 AI가 스포츠 과학 논문 데이터(RAG)를 활용하여 개인 맞춤 루틴을 생성합니다. SSE 스트리밍으로 실시간 응답을 전송합니다.

**Endpoint**

```
POST /api/v1/routines/generate
```

---

## ✅ Request

**Headers**

```
Authorization: Bearer {accessToken}
Content-Type: application/json
Accept: text/event-stream
```

**Body**

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| goals | Array<String> | ✅ | 운동 목표 (hypertrophy / strength / endurance / rehabilitation / weight_loss), 복수 선택 가능 |
| target_muscles | Array<String> | ✅ | 운동 부위 (CHEST / BACK / SHOULDER / LEGS / ABS / BICEPS / TRICEPS) |
| session_minutes | Integer | ✅ | 세션 시간 (30 / 60 / 90 / 120) |
| split_type | String | ❌ | 분할 방식 (2split / 3split / 4split / 5split), 미지정 시 AI 추천 |
| injury | String | ❌ | 부상 정보 (예: 허리 통증으로 데드리프트 제외) |
| gym_id | String (UUID) | ❌ | 사용할 헬스장 ID, 미지정 시 기본 헬스장 사용 |

**Example**

```json
{
  "goals": ["hypertrophy", "strength"],
  "target_muscles": ["CHEST", "TRICEPS"],
  "session_minutes": 75,
  "split_type": "3split",
  "injury": null,
  "gym_id": "550e8400-e29b-41d4-a716-446655440002"
}
```

---

## ✅ Response

**❗ 이 엔드포인트는 SSE (Server-Sent Events) 스트리밍으로 응답합니다.**

**Response Headers**

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**SSE 이벤트 흐름**

```
id: evt_001
data: {"type": "started", "message": "루틴 생성을 시작합니다."}

id: evt_002
data: {"type": "paper_found", "papers": [{"paper_id": "uuid", "title": "Effects of strength training frequency on muscle hypertrophy", "pmid": "31141878", "similarity": 0.84}]}

id: evt_003
data: {"type": "chunk", "content": "사용자 1RM과 보유 기구를 고려해 3분할을 추천합니다..."}

id: evt_004
data: {"type": "day_complete", "day": 1, "data": {"day_number": 1, "label": "가슴 / 삼두", "exercises": [{"exercise_id": "a1b2c3d4-...", "name": "인클라인 덤벨 프레스", "equipment": "덤벨", "sets": 4, "reps_min": 8, "reps_max": 12, "weight_kg": 22.5, "rest_seconds": 90, "has_paper": true}]}}

id: evt_005
data: {"type": "day_complete", "day": 2, "data": {"day_number": 2, "label": "등 / 이두", "exercises": [...]}}

id: evt_final
data: {"type": "done", "routine_id": "550e8400-e29b-41d4-a716-446655440000", "name": "AI 추천 3분할 (근비대)", "ai_reasoning": "..."}

data: [DONE]
```

**SSE 이벤트 타입**

| type | 의미 |
| --- | --- |
| started | 생성 시작 알림 |
| paper_found | RAG 검색으로 참조한 논문 목록 (top_k=10, similarity ≥ 0.70) |
| chunk | AI의 추론 과정 텍스트 스트리밍 |
| day_complete | Day 단위 운동 구성 완성 |
| done | 모든 Day 완성 + DB 저장 완료, routine_id 발행 |
| error | 중간 실패 (스트림 종료 직전) |

**재연결**: 클라이언트는 마지막 `id` 값을 `Last-Event-ID` 헤더로 보내 재연결 가능

**Error (400)**

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "선택한 부위에 맞는 보유 기구가 부족합니다.",
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
    "code": "ONBOARDING_REQUIRED",
    "message": "프로필 또는 1RM 정보가 필요합니다.",
    "request_id": "req_abc123"
  }
}
```

**Error (429)**

```json
{
  "success": false,
  "error": {
    "code": "RATE_LIMITED",
    "message": "요청 횟수가 초과되었습니다. 잠시 후 다시 시도해주세요.",
    "request_id": "req_abc123"
  }
}
```

**Error (503)**

```json
{
  "success": false,
  "error": {
    "code": "LLM_UNAVAILABLE",
    "message": "AI 서비스가 일시적으로 사용할 수 없습니다.",
    "request_id": "req_abc123"
  }
}
```

**SSE 시작 이후 에러** — 스트림 안에서 `error` 이벤트로 전송

```
id: evt_007
data: {"type": "error", "code": "LLM_UNAVAILABLE", "message": "AI 응답 실패", "request_id": "req_abc123"}

data: [DONE]
```
