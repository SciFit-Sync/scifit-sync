# 테스트 전략

## 백엔드 필수 테스트 (PR 머지 조건)
| 영역 | 테스트 대상 | 최소 커버리지 |
|---|---|---|
| 중량 계산 엔진 | `load_calc.py` 모든 equipment_type | 100% |
| 1RM 추정 | Epley 공식 경계값 (0, 음수, 극대값) | 100% |
| Progressive Overload | 트리거 조건, 증가량, max_stack 초과, sets 한계 | 100% |
| RAG 파이프라인 | 아래 시나리오 목록 참조 | 시나리오별 |
| 인증 | 아래 시나리오 목록 참조 | 시나리오별 |

### RAG 주요 테스트 시나리오
- 한→영 번역 성공 후 ChromaDB 검색 → 결과 반환
- 번역 실패 시 원문 직접 검색 fallback 동작
- ChromaDB 검색 결과 0건일 때 응답 처리
- threshold(0.70) 미만 결과만 있을 때 처리
- LLM API 호출 실패 시 에러 응답 (mock 사용)

### 인증 주요 테스트 시나리오
- 로그인 성공 → 토큰 발급
- 잘못된 비밀번호 → 401
- 토큰 만료 → refresh 성공
- Refresh Token Rotation + Grace Period 10초
- 폐기된 refresh token 사용 → family revoke

## 프론트엔드 테스트
- 프레임워크: Jest + React Native Testing Library
- 테스트 대상:
  - 핵심 컴포넌트 렌더링 (루틴 카드, 운동 기록 폼)
  - Zustand 스토어 상태 변경 로직
  - API 호출 mock 및 에러 처리
- 실행: `cd app && npm test`

## 테스트 파일 네이밍
- 백엔드: `server/tests/test_{모듈명}.py`, 픽스처: `server/tests/conftest.py`
- 프론트: `app/src/**/__tests__/{컴포넌트명}.test.tsx`
