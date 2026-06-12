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
| target_muscle_group_ids | Array<String> | ❌ | 운동 부위 배열 — `muscle_groups.id` UUID 또는 부위 문자열(`chest`/`back`/`shoulders`/`arms`/`legs`/`abs`/`core`) 혼용 가능. 서버가 UUID 파싱 실패 시 부위 문자열로 해석 |
| session_minutes | Integer | ❌ | 세션 시간 (분). 미지정 시 AI 추천 |
| split_type | String | ❌ | 분할 방식 (2split / 3split / 4split / 5split), 미지정 시 AI 추천 |
| injury | String | ❌ | 부상 정보 (예: 허리 통증으로 데드리프트 제외) |
| gym_id | String (UUID) | ❌ | 사용할 헬스장 ID, 미지정 시 기본 헬스장 사용 |

**Example**

```json
{
  "goals": ["hypertrophy", "strength"],
  "target_muscle_group_ids": ["<muscle_group_uuid>", "<muscle_group_uuid>"],
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
data: {"type": "started", "routine_id": "550e8400-e29b-41d4-a716-446655440000", "goals": ["hypertrophy", "strength"]}

id: evt_002
data: {"type": "chunk", "content": "사용자 1RM과 보유 기구를 고려해 3분할을 추천합니다..."}

id: evt_003
data: {"type": "day_complete", "day": 1, "data": {"routine_day_id": "b2c3d4e5-...", "day_number": 1, "label": "가슴 / 삼두", "exercises": [{"routine_exercise_id": "c3d4e5f6-...", "exercise_id": "a1b2c3d4-...", "order_index": 0, "sets": 4, "reps_min": 8, "reps_max": 12, "weight_kg": 22.5, "rest_seconds": 90, "note": "가동 범위를 충분히 확보하세요"}]}}

id: evt_004
data: {"type": "day_complete", "day": 2, "data": {"routine_day_id": "...", "day_number": 2, "label": "등 / 이두", "exercises": [...]}}

id: evt_005
data: {"type": "paper_found", "papers": [{"pmid": "31141878", "title": "Effects of strength training frequency on muscle hypertrophy", "similarity": 0.84}]}

id: evt_006
data: {"type": "done", "routine_id": "550e8400-e29b-41d4-a716-446655440000"}

data: [DONE]
```

**SSE 이벤트 타입**

| type | 의미 |
| --- | --- |
| started | 생성 시작 알림 (`routine_id`, `goals` 포함) |
| chunk | AI의 추론 과정 텍스트 스트리밍 |
| day_complete | Day 단위 운동 구성 완성 + DB 저장 (저장된 `routine_day_id`/`routine_exercise_id` 포함) |
| paper_found | RAG 검색(top_k=10, similarity ≥ 0.70) 상위 청크를 DOI 기준 dedup한 참조 논문 목록 (최대 5건, 모든 day_complete 이후 전송) |
| done | 스트림 종료. 성공 시 `routine_id` 포함, 에러 발생 시 `routine_id` 미포함 (generate 경로는 빈 루틴 삭제) |
| error | 중간 실패 (`{"type": "error", "message": "..."}` 형태) |

**재연결**: 이벤트마다 `id`(evt_NNN)가 부여되지만 서버는 `Last-Event-ID` 재개를 지원하지 않음 — 연결이 끊기면 새 생성 요청 필요

**Error (400)**

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "goals는 비어 있을 수 없습니다.",
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
    "message": "온보딩을 완료해주세요",
    "request_id": "req_abc123"
  }
}
```

**Error (429)** — rate limit 5회/분

```json
{
  "success": false,
  "error": {
    "code": "RATE_LIMITED",
    "message": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요. (5 per 1 minute)",
    "request_id": "req_abc123"
  }
}
```

**SSE 시작 이후 에러** — LLM/RAG 실패는 HTTP 에러가 아니라 스트림 안에서 `error` 이벤트로 전송 (이후 `done`에는 `routine_id` 미포함)

```
id: evt_007
data: {"type": "error", "message": "AI 응답 생성 중 오류가 발생했습니다."}

id: evt_008
data: {"type": "done"}

data: [DONE]
```
