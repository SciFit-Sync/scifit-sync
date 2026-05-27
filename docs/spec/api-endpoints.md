# API 명세 (50개)

> **상세 명세 (Request/Response 포함)**: [Notion API 명세서](https://www.notion.so/32eaebb23ee081dda33ee792957dd16d?v=335aebb23ee0808d9ad6000c2c7c2d30)
>
> **상세 명세 보완 문서**:
> - `docs/spec/api-routine-generate.md` — AI 루틴 생성 (#21) SSE 이벤트/RAG 파이프라인/논문 수집 상세
> - `docs/spec/api-exercise-swap.md` — 운동 변경 조회(#47) + 선택(#25) Request/Response 상세

**Base URL**: `/api/v1`
**인증**: `Authorization: Bearer {access_token}`

## 표준 응답
```json
{ "success": true, "data": { ... } }
{ "success": true, "data": [...], "pagination": { "total": 100, "page": 1, "limit": 20, "has_next": true } }
{ "success": false, "error": { "code": "VALIDATION_ERROR", "message": "..." } }
```

## 에러 코드

| HTTP | code |
|---|---|
| 400 | VALIDATION_ERROR |
| 401 | UNAUTHORIZED / TOKEN_EXPIRED |
| 403 | FORBIDDEN |
| 403 | ONBOARDING_REQUIRED |
| 404 | NOT_FOUND |
| 409 | EMAIL_DUPLICATE |
| 429 | RATE_LIMITED |
| 503 | LLM_UNAVAILABLE |
| 503 | EXTERNAL_API_UNAVAILABLE |

## SSE 스트리밍 포맷
```
Content-Type: text/event-stream

id: evt_001
data: {"type": "chunk", "content": "..."}

id: evt_002
data: {"type": "day_complete", "day": 1, "data": {...}}

id: evt_final
data: {"type": "done", "routine_id": "uuid"}

data: [DONE]
```

## 전체 엔드포인트

> **상태 범례**: ✅ 구현 완료 | ⚠️ 스텁(부분 구현) | ❌ 미구현

| # | Method | Path | Auth | 상태 | 비고 |
|---|---|---|---|---|---|
| 1 | POST | /auth/register | No | ⚠️ | OTP 이메일 인증 미구현 (D-01) |
| 2 | POST | /auth/login | No | ✅ | |
| 3 | POST | /auth/oauth/kakao | No | ✅ | |
| 4 | POST | /auth/logout | Yes | ✅ | |
| 5 | GET | /auth/check-username | No | ✅ | |
| 6 | POST | /auth/password/reset-email | No | ✅ | |
| 7 | PATCH | /auth/password/reset | No | ✅ | |
| 8 | DELETE | /auth/withdraw | Yes | ✅ | |
| 9 | GET | /users/me | Yes | ✅ | |
| 10 | PATCH | /users/me/body | Yes | ✅ | |
| 11 | PATCH | /users/me/goal | Yes | ✅ | |
| 12 | PATCH | /users/me/career | Yes | ✅ | |
| 13 | POST | /users/me/gym | Yes | ✅ | |
| 14 | PATCH | /users/me/gym | Yes | ✅ | |
| 16 | PATCH | /users/me/1rm | Yes | ✅ | |
| 17 | POST | /users/me/equipment | Yes | ✅ | |
| 18 | GET | /gyms?keyword= | Yes | ✅ | |
| 19 | GET | /gyms/{gymId}/equipment | Yes | ✅ | |
| 20 | POST | /gyms/{gymId}/equipment/report | Yes | ✅ | |
| 21 | POST | /routines/generate (SSE) | Yes | ⚠️ | rag.py 미구현으로 SSE 스텁 |
| 22 | GET | /routines | Yes | ✅ | |
| 23 | GET | /routines/{id} | Yes | ✅ | |
| 24 | PATCH | /routines/{id}/name | Yes | ✅ | |
| 25 | PATCH | /routines/{id}/exercises/{exId} | Yes | ✅ | |
| 26 | POST | /routines/{id}/regenerate | Yes | ⚠️ | rag.py 미구현으로 SSE 스텁 |
| 27 | DELETE | /routines/{id} | Yes | ✅ | |
| 28 | GET | /routines/{id}/exercises/{exId}/paper | Yes | ✅ | |
| 29 | GET | /home | Yes | ✅ | |
| 30 | POST | /sessions | Yes | ✅ | |
| 31 | POST | /sessions/{id}/sets | Yes | ✅ | |
| 32 | PATCH | /sessions/{id}/finish | Yes | ✅ | |
| 33 | GET | /sessions?year=&month= | Yes | ✅ | |
| 34 | GET | /sessions/stats | Yes | ✅ | |
| 35 | GET | /sessions/analysis/volume | Yes | ✅ | |
| 36 | GET | /sessions/{id}/rest-timer | Yes | ✅ | |
| 37 | POST | /chat/messages (SSE) | Yes | ⚠️ | 메시지 저장은 되나 RAG 응답 미구현 |
| 38 | GET | /chat/messages | Yes | ✅ | |
| 39 | GET | /chat/recommended-routines | Yes | ⚠️ | 빈 배열 반환 스텁 |
| 40 | GET | /notifications | Yes | ✅ | |
| 41 | PATCH | /notifications/{id}/read | Yes | ✅ | |
| 42 | POST | /auth/refresh | No | ✅ | |
| 43 | GET | /users/me/1rm | Yes | ✅ | |
| 44 | POST | /gyms | Yes | ✅ | |
| 45 | POST | /gyms/{id}/equipment | Yes | ✅ | |
| 46 | GET | /equipment | Yes | ✅ | |
| 47 | GET | /exercises | Yes | ✅ | |
| 48 | GET | /sessions/{id} | Yes | ✅ | |
| 49 | GET | /health | No | ✅ | |
| 50 | GET | /users/me/equipment | Yes | ✅ | |
| 51 | POST | /auth/verify-email | No | ✅ | 이메일 OTP 인증 (D-01) |
| 52 | POST | /auth/resend-otp | No | ✅ | OTP 재발송 (D-01) |
| 53 | GET | /equipment/brands | Yes | ✅ | 기구 브랜드 목록 |
| 54 | GET | /equipment/{equipment_id} | Yes | ✅ | 기구 단일 상세 조회 |
| 55 | POST | /equipment/select | Yes | ✅ | 온보딩 기구 선택 저장 (기존 목록 교체) |
| 56 | GET | /exercises/core-lifts | Yes | ✅ | 핵심 4대 운동(벤치/스쿼트/데드/OHP) 식별자 |
| 57 | POST | /gyms/{gym_id}/equipment/bulk | Yes | ✅ | 헬스장 기구 일괄 연결 |
| 58 | POST | /gyms/{gym_id}/equipment/suggest | Yes | ✅ | 미등록 기구 제보 |
| 59 | POST | /users/me/onboard | Yes | ✅ | 온보딩 완료 (최초 신체정보 등록) |
| 60 | POST | /users/me/1rm/bulk | Yes | ✅ | 1RM 일괄 등록 (온보딩용) |
| 61 | GET | /sessions/analysis/muscle-volume | Yes | ✅ | 근육 부위별 볼륨 분석 |

## Admin 엔드포인트 (내부용, 인증 없음)

| # | Method | Path | Auth | 상태 | 비고 |
|---|---|---|---|---|---|
| A1 | POST | /admin/rag/ingest | No | ✅ | MLOps 파이프라인 논문 청크 적재 |
| A2 | GET | /admin/rag/dois | No | ✅ | papers 테이블 DOI 목록 |
| A3 | GET | /admin/rag/pmids | No | ✅ | ChromaDB 적재된 PMID 목록 |
| A4 | POST | /admin/rag/refresh-categories | No | ✅ | ChromaDB 청크 메타 카테고리 갱신 |

## 경로 불일치 (수정 필요)

| 명세서 경로 | 실제 구현 경로 | 비고 |
|---|---|---|
| POST /auth/oauth/kakao | POST /auth/kakao | 명세서를 실제 경로에 맞춰 수정 필요 |
