# SciFit-Sync — CLAUDE.md

> Claude Code가 프로젝트 전체 컨텍스트를 파악하기 위한 기준 문서.
> 설계 결정이 변경될 때 반드시 PR 리뷰를 거쳐 업데이트할 것.

> 전체 설계서: https://www.notion.so/Scifit-Sync-33daebb23ee080f1b3aef1f7c8b416b1
> API 상세 명세서: https://www.notion.so/32eaebb23ee081dda33ee792957dd16d
> Figma 와이어프레임: https://www.figma.com/design/lowVkeYctKKWbXx7AYIa6V/캡스톤

---

## 0. 응답 규칙

- 항상 한국어로 응답한다
- 코드, 커밋 메시지, 변수명 등 영어가 관례인 부분은 예외

---

## 1. 프로젝트 개요

**SciFit-Sync** — 스포츠 과학 논문 RAG 기반 개인 맞춤형 운동 루틴 생성 모바일 앱

핵심 기능:
- 논문 기반 루틴 생성 (RAG + SSE 스트리밍)
- 도르래 비율 보정 (실효 부하 계산)
- 논문 출처 카드 AI 챗봇
- Progressive Overload 자동 제안

---

## 2. 기술 스택

| 영역 | 기술 |
|---|---|
| 모바일 | React Native + Expo Managed (Expo Go 개발, EAS Build 배포) |
| 상태 관리 | TanStack Query + Zustand |
| 네비게이션 | React Navigation 7 |
| 백엔드 | FastAPI (Python 3.11+), Pydantic v2, SQLAlchemy 2.0 async |
| DB 마이그레이션 | Alembic (단독 관리, Supabase 대시보드 직접 수정 절대 금지) |
| 관계형 DB | PostgreSQL 15 (Supabase), asyncpg 드라이버 |
| Vector DB | ChromaDB 인프로세스 (PersistentClient, /chroma-data 볼륨 필수) |
| LLM | Gemini 1.5 Flash → GPT-4o-mini (환경변수로 전환, 자동 fallback) |
| 임베딩 | BAAI/bge-large-en-v1.5 (1024차원) |
| 배포 | AWS ECS Fargate, ALB + HTTPS, EFS (/chroma-data) |
| CI/CD | GitHub Actions (PR 테스트 + 월간 논문 파이프라인) |

---

## 3. 디렉토리 구조

```
scifit-sync/
├── app/src/
│   ├── screens/      # 화면 (W코드 기준, 예: WA01Login.tsx)
│   ├── components/   # 공통 컴포넌트
│   ├── stores/       # Zustand 스토어
│   ├── services/     # API 클라이언트, SSE 클라이언트
│   └── constants/    # 디자인 토큰, 상수
├── server/app/
│   ├── api/v1/       # 라우터 (auth, users, gyms, routines, sessions, chat, notifications)
│   ├── models/       # SQLAlchemy 모델 (29개 테이블)
│   ├── schemas/      # Pydantic 스키마
│   ├── services/     # rag.py, load_calc.py, po.py, llm.py
│   └── core/         # config, database, auth, exceptions, middleware
├── mlops/pipeline/   # crawler, chunker, embedder, upserter, pg_upserter
├── mlops/scripts/    # initial_ingest.py, monthly_ingest.py
└── docs/             # spec/, guides/
```

---

## 4. 개발 명령어

```bash
# 전체 로컬 실행
docker compose up

# 백엔드만
cd server && uvicorn app.main:app --reload

# DB 마이그레이션
cd server && alembic upgrade head

# 앱
cd app && npx expo start

# 테스트
cd server && pytest tests/ -v
cd app && npm test
```

---

## 5. 아키텍처

```
[React Native + Expo]
    │  HTTPS / SSE (event_id 기반 재연결)
    ▼
[FastAPI (Python 3.11+)]
    ├── Auth Service      JWT + Refresh Token Rotation (Grace Period 10초)
    ├── Routine Service → Load Calculation Engine (load_calc.py)
    ├── Chat Service    → RAG Pipeline (rag.py)
    │                       ├── 한→영 번역 (Gemini) + fallback 원문 검색
    │                       ├── ChromaDB (top_k=10, threshold=0.70)
    │                       └── LLM 응답 (Gemini 1.5 Flash → GPT-4o-mini)
    └── Equipment Service → 카카오 로컬 API 프록시

[PostgreSQL — Supabase]  [ChromaDB — 인프로세스 /chroma-data]
```

---

## 6. 확정된 설계 결정 (D-issue)

### ✅ D-01 확정 — 회원가입 인증: 이메일 OTP
- 방식: 이메일로 6자리 숫자 OTP 발송
- 인증 완료 전까지 로그인 불가
- 화면 플로우: W-A02 정보입력 → W-OTP 인증번호입력(6자리) → W-A03 신체정보
- W-OTP 화면 신규 추가 필요 (Figma 정본화 필요)
- 이메일 발송 서비스: SendGrid 또는 AWS SES 사용
- OTP 유효시간: 10분
- phone 컬럼 없음 (SMS 방식 아님)

### ✅ D-13 확정 — phone 필드 제거
- users 테이블에 phone 컬럼 없음
- 회원가입 API Request body에 phone 필드 없음
- 절대 추가하지 말 것

### ❌ D-14 폐기 — 운동 목표 단일 선택 (D-M6로 대체)
- 폐기 사유: Program 도메인 도입 및 루틴별 복수 목표 허용 정책 전환
- 신규 정책: D-M6 참조
- 과거 정책 (참고용):
  - DB: user_profiles.fitness_goal = 단일 enum
  - API: 배열이 아닌 단일 문자열로 송수신
  - Figma 복수 선택 칩 UI와 불일치했음

### ✅ D-M6 확정 — 운동 목표 복수 선택
- DB:
  - `user_profiles.default_goals` = `text[]` (회원가입 시 선호 목표 배열)
  - `workout_routines.fitness_goals` = `text[]` (루틴별 목표 복수 허용)
- 허용 값: `'hypertrophy' | 'strength' | 'endurance' | 'rehabilitation' | 'weight_loss'`
- API: snake_case JSON 배열로 송수신
  - 예: `"default_goals": ["hypertrophy", "strength"]`
- Figma 복수 선택 칩 UI와 일치
- ⚠️ 후속 결정 필요: 복수 목표 시 PO/권장 중량 계산 기준 정책 (별도 D-issue 등록 예정)

### ✅ D-10 확정 — Program 도메인 신설 (F-7)
- 결정: Program ↔ Routine을 별도 도메인으로 분리
- 신규 테이블: `programs`, `program_routines` (N:M + `order_index`)
- 의미: 루틴(분할 단위) 위에 프로그램(다주기 묶음) 계층 추가
  예: "4주 벌크업 프로그램" = Day 분할 루틴 N개의 시퀀스
- 화면: W-M02, W-R02 영향

### ✅ D-15 확정 — API 필드명: snake_case 통일
- 프론트(TypeScript)와 백엔드(Python) 모두 snake_case 사용
- API JSON 요청/응답 필드명: snake_case
- Pydantic alias_generator 사용하지 않음
- 프론트 예시:
  ```typescript
  const { user_id, access_token, fitness_goal } = response.data
  ```
- 백엔드 예시:
  ```python
  class UserResponse(BaseModel):
      user_id: str
      access_token: str
      fitness_goal: str
  ```

---

## 7. API 설계 규칙

### Base URL
`/api/v1`

### 인증 헤더
`Authorization: Bearer {access_token}`

### 모든 ID 타입
UUID v4 문자열 (정수형 ID 절대 사용 금지)
예) `"550e8400-e29b-41d4-a716-446655440000"`

### 표준 응답 포맷 (예외 없이 적용)

```json
// 성공
{ "success": true, "data": { ... } }

// 페이지네이션
{
  "success": true,
  "data": [...],
  "pagination": { "total": 100, "page": 1, "limit": 20, "has_next": true }
}

// 에러
{
  "success": false,
  "error": { "code": "VALIDATION_ERROR", "message": "...", "details": {}, "request_id": "uuid" }
}
```

### 에러 코드 목록

| HTTP | 코드 |
|---|---|
| 400 | VALIDATION_ERROR |
| 401 | UNAUTHORIZED / TOKEN_EXPIRED |
| 403 | FORBIDDEN / ONBOARDING_REQUIRED |
| 404 | NOT_FOUND |
| 409 | EMAIL_DUPLICATE / CONFLICT |
| 429 | RATE_LIMITED |
| 503 | LLM_UNAVAILABLE / EXTERNAL_API_UNAVAILABLE |

### SSE 스트리밍 포맷

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

---

## 8. 코드 스타일

### Python (백엔드 / MLOps)
- ruff 단일 도구 (lint + format + import 정렬)
- 네이밍: snake_case (변수/함수), PascalCase (클래스), UPPER_SNAKE_CASE (상수)
- `print()` 사용 금지 → `logging` 모듈만 사용
- 에러 로그에 `request_id` 필수 포함
- 프로덕션 로그 레벨: WARNING

### TypeScript (프론트엔드)
- Prettier + ESLint (Expo 기본 설정)
- 네이밍: snake_case (변수/함수), PascalCase (컴포넌트/타입), UPPER_SNAKE_CASE (상수)
- API 응답 필드: snake_case 그대로 사용 (D-15 확정)
- 화면 파일명: W코드 기준
  - 예) `WA01Login.tsx`, `WO02Equipment.tsx`, `WR04RoutineDetail.tsx`
  - 전체 목록: `docs/spec/screens.md` 참조

---

## 9. 브랜치 전략 & 커밋 컨벤션

```
main      ← 배포 전용 (PR only, 리뷰어 1명 승인 필수)
develop   ← 개발 통합 (PR only)
feature/{이름}/{기능}  ← 기능 개발
fix/{이름}/{버그}      ← 버그 수정
```

예시:
```
feature/taehyun/auth
feature/jiyeon/fe-foundation
fix/taehyun/alembic-env
```

커밋 타입:

| 타입 | 설명 |
|---|---|
| feat | 새 기능 |
| fix | 버그 수정 |
| refactor | 리팩토링 (기능 변경 없음) |
| test | 테스트 추가/수정 |
| docs | 문서 변경 |
| chore | 기타 (의존성, 설정) |
| ci | CI/CD 변경 |

예시: `feat: JWT refresh token rotation 구현`

---

## 10. 데이터 모델 규칙

### 공통
- 모든 PK: UUID v4 (`gen_random_uuid()`)
- 모든 테이블: `created_at` + `updated_at` 자동 갱신
- DB 관리: Alembic 단독, Supabase 대시보드 직접 수정 절대 금지

### 테이블 도메인 구성 (29개)
```
User:       users, user_profiles, user_body_measurements,
            user_exercise_1rm, refresh_tokens                       (5)
Gym:        gyms, user_gyms, equipment_brands, equipments,
            gym_equipments, equipment_reports, equipment_muscles    (7)
Exercise:   exercises, exercise_equipment_map, muscle_groups,
            exercise_muscles                                        (4)
Routine:    workout_routines, routine_days, routine_exercises,
            routine_papers                                          (4)
Program:    programs, program_routines                              (2)
Workout:    workout_logs, workout_log_sets                          (2)
Chat & RAG: chat_sessions, chat_messages, papers, paper_chunks      (4)
기타:       notifications                                           (1)
```
폐기 테이블 (구버전 → 신버전 흡수 경로):
- `user_equipment_selections` → 보유 기구는 `user_gyms` + `gym_equipments` 조인으로 추론
- `user_stats` → 통계는 `workout_logs` 직접 쿼리 (집계 캐시는 별도 D-issue 결정)

### equipment 분류 (API-12: category와 equipment_type 분리)
- `equipments.category` (근육 부위 대표 1개): `'chest' | 'back' | 'shoulders' | 'arms' | 'core' | 'legs'`
- `equipments.equipment_type` (물리 타입): `'cable' | 'machine' | 'barbell' | 'dumbbell' | 'bodyweight'`
- 중량 계산 엔진은 `equipment_type` 기준 (이전 버전의 `category` 분기 코드는 마이그레이션 필요)
- 위 허용 값 외 다른 값 사용 금지

### 중량 기록
- `weight_kg` = 기구 표시값 (사용자 입력)
- 실효 부하 = `weight_kg × pulley_ratio`

### 삭제 정책
- 루틴: soft delete (`deleted_at` nullable), 복구 불가
- 나머지: hard delete

### 임베딩
- ChromaDB만 저장 (pgvector 미사용)

---

## 11. 핵심 비즈니스 로직

### 도르래 비율 보정 (`load_calc.py` 참조)

```python
def calculate_effective_weight(equipment, stack, added, body_weight):
    # API-12: category는 근육 부위, 물리 분기는 equipment_type
    match equipment.equipment_type:
        case "cable" | "machine":
            return stack * equipment.pulley_ratio + (equipment.bar_weight_kg or 0)
        case "barbell":
            return equipment.bar_weight_kg + (added or 0)
        case "dumbbell":
            return added or 0
        case "bodyweight":
            if equipment.has_weight_assist:
                return body_weight - stack
            return body_weight + (added or 0)
```

### 1RM 추정 (Epley)
```python
one_rm = effective_weight * (1 + reps / 30)
```

### 목표별 권장 중량 범위

| 목표 | 1RM 비율 | 반복 범위 |
|---|---|---|
| hypertrophy | 67~77% | 8~12 reps |
| strength | 85~95% | 1~5 reps |
| endurance | 50~65% | 15~20 reps |
| rehabilitation | 40~55% | 20~30 reps |

### Progressive Overload 트리거
- 조건: 목표 rep 상단을 연속 2세션 달성

증가량 (kg, 컬럼은 `equipment_type` 기준):

| 목표 | cable | machine | barbell | dumbbell | bodyweight |
|---|---|---|---|---|---|
| hypertrophy | 2.5 | 2.5 | 5.0 | 2.5 | 2.5 |
| strength | 5.0 | 5.0 | 5.0 | 5.0 | 5.0 |
| endurance | 1.25 | 1.25 | 1.25 | 1.25 | 1.25 |
| rehabilitation | 1.25 | 1.25 | 1.25 | 1.25 | 1.25 |

예외 처리:
- `new_weight > max_stack` → 중량 고정 + `sets + 1`
- `sets > 6` → "더 무거운 기구 사용 권장" 알림 생성

### RAG 파이프라인 흐름
```
1. 한국어 질의 수신
2. Gemini로 한→영 번역 (실패 시 원문으로 fallback — 필수 구현)
3. BAAI/bge-large-en-v1.5 임베딩 (1024차원)
4. ChromaDB 검색 (top_k=10, threshold=0.70)
   distance → similarity 변환: similarity = 1 - distance
5. 프로필 + 청크 + 가용 운동 목록 → 프롬프트 조합
6. Gemini 1.5 Flash SSE 스트리밍 (fallback: GPT-4o-mini)
7. exercise_id DB 존재 검증 (없으면 제외 또는 이름 기반 fallback)
8. load_calc으로 중량 계산 → DB 저장
```

---

## 12. 보안 정책

### JWT
- Access Token: 1시간
- Refresh Token: 30일 + Rotation
- Grace Period: 10초 (race condition 방지)
- Family Revoke: 탈취 감지 시 동일 family 전체 무효화
- SSE 연결 전: 만료까지 5분 미만이면 사전 refresh (클라이언트 처리)

### Rate Limit (slowapi)
- 인증 엔드포인트: 분당 10회
- 일반 엔드포인트: 분당 60회
- LLM 엔드포인트: 분당 5회 (`/routines/generate`, `/chat/messages`)

### 프롬프트 인젝션 방어
- 사용자 입력은 항상 `<user_query>` 태그로 격리
  ```
  <user_query>{사용자 입력}</user_query>
  ```
- raw 문자열로 프롬프트에 직접 삽입 절대 금지

### 프로덕션 노출 금지
- 스택 트레이스, SQL 쿼리, 파일 경로, API 키, 환경변수 값

---

## 13. 테스트 규칙

### 필수 100% 커버리지
- `server/app/services/load_calc.py`
- `server/app/services/po.py`
- `server/app/services/rag.py` 중 `search_chunks`

### 실행 명령
```bash
cd server && pytest tests/ -v
cd server && pytest tests/ --cov=app --cov-report=html
cd mlops && pytest tests/ -v
cd app && npm test
```

### CI 외부 API mock 처리
- NCBI, Gemini, 카카오 API 호출은 반드시 mock
- 실제 API 키 없이도 CI 통과 필수

---

## 14. 디자인 시스템

기준 디바이스: iPhone 14 (393×852pt)
폰트: Pretendard

### 컬러
| 용도 | 값 |
|---|---|
| Primary 버튼 배경 | #000000 |
| Primary 버튼 텍스트 | #FFFFFF |
| 카카오 버튼 배경 | #FEE500 |
| 카카오 버튼 텍스트 | #000000 |
| 입력 필드 배경 | #F7F7F7 |
| 입력 필드 테두리 | #CCCCCC |
| AI 인사이트 배경 | #F0E6FF |
| 선택된 칩 배경 | #000000 |
| 선택된 칩 텍스트 | #FFFFFF |

### 1RM dot 색상
| 운동 | 색상 |
|---|---|
| 벤치프레스 | 파란색 |
| 스쿼트 | 초록색 |
| 데드리프트 | 주황색 |
| 오버헤드프레스 | 보라색 |

### 컴포넌트 스펙
```
PrimaryButton: bg=#000, radius=8, height=44
KakaoButton:   bg=#FEE500, radius=8, height=44
TextInput:     height=40, bg=#F7F7F7, border=#CCC, radius=6
ChipSelector:  선택 시 bg=#000 text white
```

### 하단 탭 순서
챗봇 | 분석 | 메인(홈) | 기록 | 마이페이지

---

## 15. 절대 금지 사항

- Supabase 대시보드 직접 DB 스키마 수정 → Alembic만 사용
- `.env` 파일 커밋 → `.gitignore` 확인 필수
- `git push --force` / `git reset --hard` (공유 브랜치에서)
- `npm audit fix --force`
- `--no-verify` 플래그 사용
- 프로덕션 환경 `/docs` 활성화 → IP 제한 또는 비활성화
- AWS 배포 시 `/chroma-data` 스토리지 없이 배포 → 데이터 소실
- LLM에 사용자 입력 raw 전달 → `<user_query>` 태그 필수
- ECS 멀티 태스크 배포 → Task count=1 유지 (ChromaDB 동시 접근 금지)
- 테스트 없이 main/develop PR → CI 통과 필수
- CLAUDE.md 팀 합의 없이 단독 수정 → PR 리뷰 필수

---

## 16. 미결정 사항 (D-issue)

| ID | 주제 | 현재 상태 |
|---|---|---|
| D-02 | PO 제안 바텀시트(W-L03) 구현 여부 | 미정 |
| D-05 | 소셜 로그인 확장 (네이버/Google/Apple) | 미정 (카카오만 명세) |
| D-06 | 주당 운동 일수 UI (슬라이더 vs 칩) | 미정 |
| D-07 | 나이 입력 방식 (숫자 vs Date Picker) | 미정 |
| D-09 | 근육 회복도 계산 기준 | 미정 |
| D-MX | 복수 목표 시 PO/권장 중량 계산 기준 (D-M6 후속) | 미정 |

---

## 17. 참조 문서

| 문서 | 경로 |
|---|---|
| API 전체 명세 50개 | `docs/spec/api-endpoints.md` |
| DB 스키마 29테이블 | `docs/spec/database-schema.md` |
| 화면 목록 25개+ | `docs/spec/screens.md` |
| 환경 셋업 가이드 | `docs/guides/environment-setup.md` |
| 테스트 전략 | `docs/guides/testing-strategy.md` |
| 배포 + CI/CD | `docs/guides/deployment.md` |
| 에러 핸들링 | `docs/guides/error-handling.md` |
