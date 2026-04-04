# 에러 핸들링 상세

## 응답 구조
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "이메일 형식이 올바르지 않습니다",
    "details": {"field": "email"},
    "request_id": "req_abc123"
  }
}
```

## 에러 코드 매핑
| 코드 | HTTP | 용도 |
|---|---|---|
| VALIDATION_ERROR | 400 | 입력 검증 실패 |
| UNAUTHORIZED | 401 | 인증 실패/토큰 만료 |
| FORBIDDEN | 403 | 권한 부족 |
| NOT_FOUND | 404 | 리소스 미존재 |
| CONFLICT | 409 | 중복/상태 충돌 (예: 이미 등록된 이메일) |
| RATE_LIMITED | 429 | 요청 제한 초과 |
| INTERNAL_ERROR | 500 | 서버 내부 오류 |

## 구현 위치
| 파일 | 역할 |
|---|---|
| `server/app/core/exceptions.py` | AppError 기본 클래스 + 에러 카테고리별 서브클래스 |
| `server/app/core/exception_handlers.py` | 전역 핸들러 (`app.add_exception_handler`로 등록) |
| `server/app/core/middleware.py` | request_id 생성 미들웨어 (UUID → `request.state.request_id`) |

## 프로젝트 고유 에러 시나리오
| 시나리오 | 에러 코드 | 대응 |
|---|---|---|
| ChromaDB 연결 실패 | INTERNAL_ERROR | 로그 기록 + 사용자에게 "잠시 후 재시도" 응답 |
| LLM API 할당량 초과 | RATE_LIMITED | 대체 모델(GPT-4o-mini ↔ Gemini) 자동 전환 |
| 도르래 비율 범위 초과 (0 이하, 10 초과) | VALIDATION_ERROR | 기구 데이터 확인 요청 |
| SSE 스트리밍 중 연결 끊김 | — | `event_id` 기반 재연결, 마지막 이벤트부터 재전송 |
| Supabase 연결 타임아웃 | INTERNAL_ERROR | 재시도 3회 후 실패 응답 |

## 프로덕션 금지 노출 항목
- 스택 트레이스, SQL 쿼리, 파일 경로, API 키, DB 연결 문자열
