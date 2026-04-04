# SciFit-Sync — CLAUDE.md

> Claude Code가 프로젝트 전체 컨텍스트를 파악하기 위한 기준 문서입니다.
> 설계 결정이 변경될 때 반드시 업데이트하세요.

## 0. 응답 규칙
- **항상 한국어로 응답한다.** 코드, 커밋 메시지, 변수명 등 영어가 관례인 부분은 예외.
>
> 상세 설계서: https://www.notion.so/338aebb23ee081af885ecdda757047d5
> Figma 와이어프레임: https://www.figma.com/design/lowVkeYctKKWbXx7AYIa6V/캡스톤\?node-id\=276-822

---

## 1. 프로젝트 개요

**SciFit-Sync** — 스포츠 과학 논문 RAG 기반 개인 맞춤형 운동 루틴 생성 모바일 앱
핵심: 논문 근거 루틴 생성 (RAG) / 도르래 비율 보정 / 논문 출처 카드 챗봇

---

## 2. 기술 스택

| 영역 | 선택 | 비고 |
|---|---|---|
| 모바일 | React Native + Expo Managed | Expo Go 개발, EAS Build 배포 |
| 상태 관리 | TanStack Query + Zustand | |
| 백엔드 | FastAPI (Python 3.11+) | Pydantic v2, SQLAlchemy 2.0 async |
| DB 마이그레이션 | Alembic | 단독 관리, Supabase 대시보드 직접 수정 금지 |
| 관계형 DB | PostgreSQL (Supabase) | |
| Vector DB | ChromaDB 인프로세스 | PersistentClient(), /chroma-data 볼륨 필수 |
| LLM | Gemini 1.5 Flash → GPT-4o-mini | 환경변수로 교체 |
| 임베딩 | BAAI/bge-large-en-v1.5 | 1024차원 |
| 배포 | AWS (EC2/ECS) | Docker 이미지 배포 |
| MLOps | GitHub Actions Cron | 월 1회 자동 |
| 청킹 | 자체 구현 Section-Aware | 300~512 토큰, overlap 50 |

---

## 3. 디렉토리 구조
```
scifiit-sync/
├── app/src/              # React Native (screens/, components/, stores/, services/, constants/)
├── server/app/           # FastAPI
│   ├── api/v1/           # 엔드포인트 (auth, users, routines, gyms, sessions, chat, notifications)
│   ├── models/           # SQLAlchemy 모델
│   ├── schemas/          # Pydantic Request/Response
│   ├── services/         # rag.py, load_calc.py, po.py
│   └── core/             # 설정, 인증, DB, exceptions, middleware
├── server/alembic/       # DB 마이그레이션
├── server/tests/         # pytest
├── mlops/pipeline/       # crawler, chunker, embedder, upserter
├── mlops/scripts/        # initial_ingest.py, monthly_ingest.py
└── docs/                 # spec/, guides/
```

---

## 4. 개발 명령어
```bash
docker compose up                              # 전체 로컬 실행
cd server && uvicorn app.main:app --reload      # 백엔드만
cd app && npx expo start                        # 앱만
cd server && alembic upgrade head               # DB 마이그레이션
cd server && pytest tests/ -v                   # 테스트
```

---

## 5. 아키텍처
```
[React Native + Expo]
    │  HTTPS / SSE (event_id 기반 재연결)
    ▼
[FastAPI (Python 3.11+)]
    ├── Auth Service      JWT + Refresh Token Rotation (Grace Period 10초)
    ├── Routine Service → Load Calculation Engine
    ├── Chat Service    → RAG Pipeline
    │                       ├── 한→영 번역 (Gemini) + fallback 원문 검색
    │                       ├── ChromaDB (top_k=10, threshold=0.70)
    │                       └── LLM 응답 (Gemini 1.5 Flash → GPT-4o-mini fallback)
    └── Equipment Service → 카카오 로컬 API 프록시

[PostgreSQL — Supabase]  [ChromaDB — 인프로세스 /chroma-data]
```

---

## 6. 핵심 비즈니스 로직

### 도르래 비율 보정
```python
def calculate_effective_weight(equipment, stack=None, added=None, body=None):
    match equipment.category:
        case "cable" | "machine":
            return stack * equipment.pulley_ratio + (equipment.bar_weight_kg or 0)
        case "barbell":
            return equipment.bar_weight_kg + (added or 0)
        case "dumbbell":
            return added or 0
        case "bodyweight":
            if equipment.has_weight_assist:
                return body - stack
            return body + (added or 0)
```

### 1RM 추정 (Epley)
```python
one_rm = effective_weight * (1 + reps / 30)
```

### 목표별 권장 중량 범위
```python
RANGES = {
    "hypertrophy":    (0.67, 0.77),  # 8-12 reps
    "strength":       (0.85, 0.95),  # 1-5 reps
    "endurance":      (0.50, 0.65),  # 15-20 reps
    "rehabilitation": (0.40, 0.55),  # 20-30 reps
}
```

### Progressive Overload
```python
# 트리거: 목표 rep 상단 연속 2세션 달성
INCREASE = {
    "hypertrophy": {"cable": 2.5, "barbell": 5.0},
    "strength":    {"cable": 5.0, "barbell": 5.0},
    "endurance":   {"cable": 1.25, "barbell": 1.25},
}
# max_stack 초과 → 중량 고정 + sets+1
# sets > 6 → "더 무거운 기구 사용 권장" 알림
```

### RAG 파이프라인
```
1. 목표 + 프로필 수신
2. 한→영 번역 (Gemini) — 실패 시 원문 직접 검색
3. 임베딩 변환 (BAAI/bge-large-en-v1.5)
4. ChromaDB Top-K (top_k=10, threshold=0.70)
5. chunks + 프로필 + 가용 운동 목록 → 프롬프트
6. LLM day 단위 JSON 스트리밍 (SSE)
7. 서버 validation → 중량 계산 → 저장 & 반환
```

---

## 7. API 규칙

- 표준 응답: `{ success, data }` / 에러: `{ success: false, error: { code, message } }`
- SSE 스트리밍: `event_id` 기반 재연결, `data: [DONE]`으로 종료
- 전체 엔드포인트 목록: `docs/spec/api-endpoints.md`

---

## 8. 데이터 모델

- 27개 테이블 (users, equipments, exercises, routines, workout_logs, papers 등)
- equipment.category: cable / machine / barbell / dumbbell / bodyweight
- 중량 기록: weight_kg = 표시값, 실효 부하 = weight_kg × pulley_ratio
- 루틴 삭제: soft delete (deleted_at)
- 임베딩: ChromaDB만 (pgvector 미사용)
- 전체 스키마: `docs/spec/database-schema.md`

---

## 9. 보안 정책

- 로그인 실패 5회 → 15분 잠금
- JWT 1시간, SSE 연결 전 잔여 5분 미만 시 사전 refresh
- Refresh 30일 + Rotation, Grace Period 10초, family revoke
- Rate Limit: 인증 분당 10회 / 일반 60회 / LLM 5회
- 프롬프트 인젝션: 사용자 입력 <user_query> 태그로 격리

---

## 10. 브랜치 전략 & 커밋 컨벤션
```
main      ← 배포 (PR only, 승인 1명)
develop   ← 개발 통합 (PR only)
feature/{이름}/{기능}
fix/{이름}/{버그}
```
커밋 타입: `feat` / `fix` / `refactor` / `docs` / `test` / `style` / `chore` / `ci`

---

## 11. 코드 스타일

- Python: **ruff** 단일 도구 (lint + format + import 정렬)
- TypeScript: Prettier + ESLint (Expo 기본)
- 네이밍: snake_case (Python), camelCase (TS), PascalCase (컴포넌트), UPPER_SNAKE_CASE (상수)
- 화면 파일명: W코드 기준 (예: `WA01Login.tsx`, 목록은 `docs/spec/screens.md`)
- CI: `ruff check` + `ruff format --check` → 실패 시 머지 차단

---

## 12. 에러 핸들링

- 응답: `{ error: { code, message, details, request_id } }`
- 에러 코드: VALIDATION_ERROR(400) / UNAUTHORIZED(401) / FORBIDDEN(403) / NOT_FOUND(404) / CONFLICT(409) / RATE_LIMITED(429) / INTERNAL_ERROR(500)
- 구현: `server/app/core/exceptions.py` (AppError) + `exception_handlers.py` (전역) + `middleware.py` (request_id)
- 프로덕션 노출 금지: 스택 트레이스, SQL, 파일 경로, API 키
- 로깅: `print()` 금지 → `logging` 모듈 사용, 에러 로그에 `request_id` 필수, 프로덕션 레벨 WARNING
- 상세: `docs/guides/error-handling.md`

---

## 13. 테스트

- 백엔드: `pytest tests/ -v` / 프론트: `npm test`
- 필수 100% 커버리지: 중량 계산, 1RM, Progressive Overload
- 상세 시나리오: `docs/guides/testing-strategy.md`

---

## 14. 절대 금지 사항

- Supabase 대시보드 직접 DB 스키마 수정 → Alembic만 사용
- 프로덕션 /docs 활성화 → IP 제한 또는 비활성화
- AWS 배포 시 /chroma-data 스토리지 없이 배포 → 데이터 소실
- LLM에 사용자 입력 raw 전달 → <user_query> 태그 필수
- .env 파일 커밋 → .gitignore 확인
- `git push --force` / `git reset --hard` on shared branches
- `npm audit fix --force`
- 테스트 없이 main/develop 머지 → CI 통과 필수
- CLAUDE.md 설계 변경 시 팀 합의 없이 수정 → PR 리뷰 필수
- ECS 멀티 태스크 배포 시 ChromaDB 동시 접근 → 단일 인스턴스(Task count=1)만 허용

---

## 15. 미결정 사항

| ID | 주제 | 결정 필요 |
|---|---|---|
| D-01 | 회원가입 인증 | SMS vs 이메일 OTP |
| D-02 | PO 제안 바텀시트(W-L03) | 구현 여부 |
| ~~D-03~~ | ~~(해결됨)~~ | — |
| ~~D-04~~ | ~~(해결됨)~~ | — |
| D-05 | 소셜 로그인 확장 | 네이버/Google/Apple |
| D-06 | 주당 운동 일수 UI | 슬라이더 vs 칩 |
| D-07 | 나이 입력 | 숫자 vs Date Picker |
| ~~D-08~~ | ~~(해결됨)~~ | — |
| D-09 | 근육 회복도 계산 | 계산 기준 미정 |
| D-10 | Program vs Routine 관계 | W-M02/W-R02 화면 존재, API 미정의 |
| D-11 | rehabilitation PO 전략 | RANGES에만 존재, INCREASE 미정의 |
| D-12 | PO 증가량: machine/dumbbell/bodyweight | INCREASE에 cable/barbell만 정의 |

---

## 참조 문서

| 문서 | 경로 |
|---|---|
| API 전체 명세 (50개) | `docs/spec/api-endpoints.md` |
| DB 스키마 (27개 테이블) | `docs/spec/database-schema.md` |
| 화면 목록 (23개) | `docs/spec/screens.md` |
| 환경 셋업 가이드 | `docs/guides/environment-setup.md` |
| 테스트 전략 상세 | `docs/guides/testing-strategy.md` |
| 배포 + CI/CD + 모니터링 | `docs/guides/deployment.md` |
| 에러 핸들링 상세 | `docs/guides/error-handling.md` |
