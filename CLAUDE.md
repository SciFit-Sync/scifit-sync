# SciFit-Sync — CLAUDE.md

> Claude Code가 프로젝트 전체 컨텍스트를 파악하기 위한 기준 문서입니다.
> 설계 결정이 변경될 때 반드시 업데이트하세요.
>
> 상세 설계서: https://www.notion.so/338aebb23ee081af885ecdda757047d5
> Figma 와이어프레임: https://www.figma.com/design/lowVkeYctKKWbXx7AYIa6V/캡스톤\?node-id\=276-822

---

## 1. 프로젝트 개요

**SciFit-Sync** — 스포츠 과학 논문 RAG 기반 개인 맞춤형 운동 루틴 생성 모바일 앱
슬로건: "당신의 운동에 근거를 더하다"

핵심 차별점:
- 논문 근거 기반 루틴 생성 (RAG)
- 헬스장 기구 도르래 비율 보정 자동 계산
- 논문 출처 카드 첨부 챗봇 답변

팀: 6명 | 기간: 16주 1학기 캡스톤

---

## 2. 기술 스택 (확정)

| 영역 | 선택 | 비고 |
|---|---|---|
| 모바일 | React Native + Expo Managed | Expo Go 개발, EAS Build 배포 |
| 상태 관리 | TanStack Query + Zustand | |
| 백엔드 | FastAPI (Python 3.11+) | Pydantic v2, SQLAlchemy 2.0 async |
| DB 마이그레이션 | Alembic | 단독 관리, Supabase 대시보드 직접 수정 금지 |
| 관계형 DB | PostgreSQL (Supabase) | |
| Vector DB | ChromaDB 인프로세스 | PersistentClient(), /chroma-data 볼륨 필수 |
| LLM | Gemini 1.5 Flash → GPT-4o-mini | 환경변수로 교체 |
| 임베딩 | BAAI/bge-large-en-v1.5 | 1024차원, passage retrieval 특화 |
| 배포 | AWS (EC2/ECS) | Docker 이미지 배포 |
| MLOps | GitHub Actions Cron | 월 1회 자동 |
| 지도 | 카카오 로컬 API | 백엔드 프록시 |
| 로컬 개발 | Docker Compose | |
| 청킹 | 자체 구현 Section-Aware | 300~512 토큰, overlap 50 |
| 테스트 | pytest | 중량 계산·RAG 단위 테스트 필수 |

---

## 3. 디렉토리 구조
```
scifiit-sync/
├── CLAUDE.md
├── docker-compose.yml
├── .github/
│   ├── workflows/
│   │   ├── test.yml          # PR 자동 테스트
│   │   └── mlops.yml         # 월 1회 논문 파이프라인
│   ├── ISSUE_TEMPLATE/
│   ├── CODEOWNERS
│   └── pull_request_template.md
├── app/                      # React Native + Expo
│   └── src/
│       ├── screens/          # 파일명: W코드 기준 (예: WA01Splash.tsx)
│       ├── components/       # 공통 컴포넌트
│       ├── stores/           # Zustand 스토어
│       ├── services/         # API 호출 (TanStack Query)
│       └── constants/        # 색상, 폰트, 디자인 토큰
├── server/                   # FastAPI 백엔드
│   ├── app/
│   │   ├── main.py
│   │   ├── api/v1/           # 엔드포인트 (도메인별)
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── routines.py
│   │   │   ├── gyms.py
│   │   │   ├── sessions.py
│   │   │   ├── chat.py
│   │   │   └── notifications.py
│   │   ├── models/           # SQLAlchemy 모델
│   │   ├── schemas/          # Pydantic Request/Response
│   │   ├── services/
│   │   │   ├── rag.py        # RAG 파이프라인
│   │   │   ├── load_calc.py  # 중량 계산 엔진
│   │   │   └── po.py         # Progressive Overload
│   │   └── core/             # 설정, 인증, DB 연결
│   ├── alembic/
│   ├── tests/
│   ├── .env.example
│   └── requirements.txt
├── mlops/
│   ├── pipeline/
│   │   ├── crawler.py        # PubMed/PMC 크롤러
│   │   ├── chunker.py        # 자체 청킹
│   │   ├── embedder.py       # BAAI/bge-large-en-v1.5
│   │   └── upserter.py       # ChromaDB upsert
│   ├── scripts/
│   │   └── initial_ingest.py # 초기 데이터 구축 (일회성)
│   └── requirements.txt
└── docs/
```

---

## 4. 개발 명령어
```bash
# 전체 로컬 실행
docker-compose up

# 백엔드만
cd server && uvicorn app.main:app --reload

# 앱만
cd app && npx expo start

# DB 마이그레이션
cd server && alembic upgrade head

# 테스트 실행
cd server && pytest tests/ -v

# 새 마이그레이션 생성
cd server && alembic revision --autogenerate -m "설명"
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
    │                       └── LLM 응답 (Gemini 1.5 Flash)
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

## 7. API 명세 (49개)

**Base URL**: `/api/v1`
**인증**: `Authorization: Bearer {access_token}`

### 표준 응답
```json
{ "success": true, "data": { ... } }
{ "success": true, "data": [...], "pagination": { "total": 100, "page": 1, "limit": 20, "has_next": true } }
{ "success": false, "error": { "code": "VALIDATION_ERROR", "message": "..." } }
```

### 에러 코드

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

### 전체 엔드포인트

| # | Method | Path | Auth |
|---|---|---|---|
| 1 | POST | /auth/register | No |
| 2 | POST | /auth/login | No |
| 3 | POST | /auth/oauth/kakao | No |
| 4 | POST | /auth/logout | Yes |
| 5 | GET | /auth/check-username | No |
| 6 | POST | /auth/password/reset-email | No |
| 7 | PATCH | /auth/password/reset | No |
| 8 | DELETE | /auth/withdraw | Yes |
| 9 | GET | /users/me | Yes |
| 10 | PATCH | /users/me/body | Yes |
| 11 | PATCH | /users/me/goal | Yes |
| 12 | PATCH | /users/me/career | Yes |
| 13 | POST | /users/me/gym | Yes |
| 14 | PATCH | /users/me/gym | Yes |
| 15 | POST | /users/me/1rm | Yes |
| 16 | PATCH | /users/me/1rm | Yes |
| 17 | POST | /users/me/equipment | Yes |
| 18 | GET | /gyms?keyword= | Yes |
| 19 | GET | /gyms/{gymId}/equipment | Yes |
| 20 | POST | /gyms/{gymId}/equipment/report | Yes |
| 21 | POST | /routines/generate (SSE) | Yes |
| 22 | GET | /routines | Yes |
| 23 | GET | /routines/{id} | Yes |
| 24 | PATCH | /routines/{id}/name | Yes |
| 25 | PATCH | /routines/{id}/exercises/{exId} | Yes |
| 26 | POST | /routines/{id}/regenerate | Yes |
| 27 | DELETE | /routines/{id} | Yes |
| 28 | GET | /routines/{id}/exercises/{exId}/paper | Yes |
| 29 | GET | /home | Yes |
| 30 | POST | /sessions | Yes |
| 31 | POST | /sessions/{id}/sets | Yes |
| 32 | PATCH | /sessions/{id}/finish | Yes |
| 33 | GET | /sessions?year=&month= | Yes |
| 34 | GET | /sessions/stats | Yes |
| 35 | GET | /sessions/analysis/volume | Yes |
| 36 | GET | /sessions/{id}/rest-timer | Yes |
| 37 | POST | /chat/messages (SSE) | Yes |
| 38 | GET | /chat/messages | Yes |
| 39 | GET | /chat/recommended-routines | Yes |
| 40 | GET | /notifications | Yes |
| 41 | PATCH | /notifications/{id}/read | Yes |
| 42 | POST | /auth/refresh | No |
| 43 | GET | /users/me/1rm | Yes |
| 44 | POST | /gyms | Yes |
| 45 | POST | /gyms/{id}/equipment | Yes |
| 46 | GET | /equipment | Yes |
| 47 | GET | /exercises | Yes |
| 48 | GET | /sessions/{id} | Yes |
| 49 | GET | /health | No |

---

## 8. 데이터 모델 (27개 테이블)
```
사용자: users, user_profiles, user_body_measurements,
        user_exercise_1rm, refresh_tokens, user_equipment_selections

헬스장: gyms, user_gyms, equipment_brands, equipments,
        gym_equipments, equipment_reports

운동:   exercises, exercise_equipment_map, muscle_groups, exercise_muscles

루틴:   workout_routines, routine_days, routine_exercises, routine_papers

기록:   workout_logs, workout_log_sets

RAG:    chat_sessions, chat_messages, papers, paper_chunks

기타:   notifications, user_stats
```

### 주요 설계 결정

- equipment.category: cable / machine / barbell / dumbbell / bodyweight
- 중량 기록: weight_kg = 기구 표시값, 실효 부하 = weight_kg × pulley_ratio
- 루틴 삭제: soft delete (deleted_at), 복구 불가
- RAG: 임베딩은 ChromaDB만 저장 (pgvector 미사용)
- DB: Alembic 단독 관리, Supabase 대시보드 직접 수정 금지

---

## 9. 화면 목록 (23개)

| ID | 화면명 | Figma 노드 | 우선순위 |
|---|---|---|---|
| W-S01 | 스플래시 | 276:823 | Must |
| W-A01 | 로그인 | 276:833 | Must |
| W-A02 | 회원가입-정보입력 | 276:853 | Must |
| W-A03 | 회원가입-신체정보 | 276:877 | Must |
| W-A04 | 비밀번호재설정 | 276:919 | Must |
| W-O01-A | 헬스장설정(동의 전) | 276:981 | Must |
| W-O01-B | 헬스장설정(동의 후) | 276:938 | Must |
| W-O02 | 기구설정 | 276:1008 | Must |
| W-O02-R | 기구등록 | 301:1863 | Must |
| W-O03 | 1RM설정 | 276:1066 | Must |
| W-M01 | 메인-단일루틴 | 276:1276 | Must |
| W-M02 | 메인-프로그램 | 276:1322 | Should |
| W-R01 | 루틴생성 | 276:1372 | Must |
| W-R02 | 프로그램생성 | 286:1789 | Should |
| W-R03 | 루틴생성중 | 276:1419 | Must |
| W-R04 | 루틴상세(스크롤) | 276:1131 | Must |
| W-C01 | 챗봇 | 276:1444 | Must |
| W-H01 | 기록-캘린더 | 276:1485 | Should |
| W-H02 | 분석 | 276:1615 | Should |
| W-N01 | 알림 | 276:1103 | Nice |
| W-P01 | 마이페이지 | 276:1647 | Must |
| W-P02 | 로그아웃모달 | 276:1685 | Must |
| W-P03 | 탈퇴페이지 | 276:1699 | Must |

하단 네비: 챗봇 | 분석 | **메인** | 기록 | 마이

디자인 시스템:
- 기준: iPhone 14 (393×852pt)
- 폰트: Pretendard
- Primary 버튼: #000000, r=8, h=44
- 입력 필드: h=40, bg=#F7F7F7, border=#CCC, r=6
- AI 인사이트: #F0E6FF
- 1RM dot: 벤치🔵 스쿼트🟢 데드🟠

---

## 10. 보안 정책

- 로그인 실패 5회 → 15분 잠금
- OTP 유효 5분, 5회 시도 제한
- JWT 1시간, SSE 연결 전 잔여 5분 미만 시 사전 refresh
- Refresh 30일 + Rotation, Grace Period 10초, family revoke
- Rate Limit: 인증 분당 10회 / 일반 60회 / LLM 5회
- 프롬프트 인젝션: 사용자 입력 <user_query> 태그로 격리

---

## 11. 브랜치 전략 & 커밋 컨벤션
```
main      ← 배포 (PR only, 승인 1명)
develop   ← 개발 통합 (PR only)
feature/{이름}/{기능}
fix/{이름}/{버그}
```

커밋:
```
feat: 루틴 생성 SSE 스트리밍 구현
fix: 1RM 도르래 비율 계산 오류 수정
docs: API 명세 업데이트
test: 중량 계산 엔진 단위 테스트
chore: 의존성 업데이트
```

---

## 12. 절대 금지 사항

- Supabase 대시보드 직접 DB 스키마 수정 → Alembic만 사용
- 프로덕션 /docs 활성화 → IP 제한 또는 비활성화
- AWS 배포 시 /chroma-data 스토리지 없이 배포 → 데이터 소실
- LLM에 사용자 입력 raw 전달 → <user_query> 태그 필수
- .env 파일 커밋 → .gitignore 확인
- `git push --force` 또는 `git push -f` → 히스토리 파괴
- `git reset --hard` on shared branches → 다른 팀원 작업 소실
- `npm audit fix --force` → 의존성 깨짐 위험
- 테스트 없이 main/develop 머지 → CI 통과 필수
- CLAUDE.md 설계 변경 시 팀 합의 없이 수정 → 반드시 PR 리뷰

---

## 13. 미결정 사항

| ID | 주제 | 결정 필요 |
|---|---|---|
| D-01 | 회원가입 인증 | SMS vs 이메일 OTP |
| D-02 | PO 제안 바텀시트(W-L03) | 구현 여부 |
| D-05 | 소셜 로그인 확장 | 네이버/Google/Apple |
| D-06 | 주당 운동 일수 UI | 슬라이더 vs 칩 |
| D-07 | 나이 입력 | 숫자 vs Date Picker |
| D-09 | 근육 회복도 계산 | 계산 기준 미정 |

---

## 14. 환경 셋업 (신규 팀원)

### 사전 요구사항
- Python 3.11+
- Node.js 18+ / npm 9+
- Docker Desktop (Windows: WSL2 백엔드 활성화 필수)
- Expo Go 앱 (모바일 테스트용, iOS/Android)
- Git

### Docker 서비스 구성
| 서비스 | 이미지 | 포트 | 비고 |
|---|---|---|---|
| server | `./server` (빌드) | 8000 | FastAPI |
| db | `postgres:15-alpine` | 5432 | 로컬 개발 DB |

> ChromaDB는 FastAPI 서버 내 인프로세스(`PersistentClient`)로 동작하며, `/chroma-data` 볼륨에 데이터 저장

### 첫 설정

```bash
# 1. 리포 클론
git clone https://github.com/SciFit-Sync/scifiit-sync.git
cd scifiit-sync
git checkout develop
```

```bash
# 2. 서버 환경변수 설정
cp server/.env.example server/.env
# → .env 파일에 실제 키 입력 (아래 시크릿 획득처 참고)
```

```bash
# 3. 앱 환경변수 설정
cp app/.env.example app/.env
# → API_BASE_URL=http://localhost:8000 (로컬 기본값)
```

```bash
# 4. pre-commit 설정
pip install pre-commit
pre-commit install
detect-secrets scan > .secrets.baseline
```

```bash
# 5. Docker로 전체 실행
docker compose up
```

```bash
# 6. DB 마이그레이션
docker compose exec server alembic upgrade head
```

```bash
# 7. 앱 실행 (별도 터미널)
cd app && npm install && npx expo start
```

### 환경변수 전체 목록

| 변수명 | 설명 | 필수 | 획득처 |
|---|---|---|---|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | Y | Supabase 대시보드 > Settings > Database |
| `SUPABASE_URL` | Supabase 프로젝트 URL | Y | Supabase 대시보드 > Settings > API |
| `SUPABASE_ANON_KEY` | Supabase anon key | Y | Supabase 대시보드 > Settings > API |
| `JWT_SECRET_KEY` | JWT 서명 키 | Y | `openssl rand -hex 32`로 생성 |
| `JWT_ALGORITHM` | JWT 알고리즘 | Y | 기본값: `HS256` |
| `GEMINI_API_KEY` | Gemini API 키 | Y | Google AI Studio |
| `OPENAI_API_KEY` | GPT-4o-mini 폴백 키 | N | OpenAI 대시보드 |
| `KAKAO_REST_API_KEY` | 카카오 로컬 API 키 | Y | Kakao Developers 앱 > 앱 키 |
| `CHROMA_PERSIST_PATH` | ChromaDB 데이터 경로 | Y | 기본값: `/chroma-data` |
| `ENV` | 실행 환경 | Y | `development` / `production` |
| `API_BASE_URL` (앱) | 서버 API URL | Y | 로컬: `http://localhost:8000` |

### 시크릿 공유 정책
- 시크릿은 **팀 공유 1Password** 또는 **암호화된 채널**로만 공유
- Notion 페이지에 API 키 직접 기재 금지
- 각자 개인 키 발급 권장 (Gemini, Kakao 등)

### 플랫폼별 주의사항
| 환경 | 주의 |
|---|---|
| Windows (WSL2) | Docker Desktop WSL2 Integration 활성화 필수. Expo는 WSL 내부가 아닌 PowerShell에서 실행 권장 |
| Mac (Apple Silicon) | `pip install` 시 일부 패키지 arm64 빌드 이슈 가능 → `--platform` 플래그 또는 Rosetta 사용 |
| Linux | Docker는 `sudo` 없이 사용하도록 그룹 추가: `sudo usermod -aG docker $USER` |

---

## 15. 코드 스타일

### Python (server/, mlops/)
- 린트 + 포매팅 + import 정렬: **ruff 단일 도구** (black 호환 포매팅, isort 호환 정렬 내장)
- 타입 체크: mypy (점진적 채택 — `--warn-return-any`, `--disallow-untyped-defs`부터 시작)

### TypeScript (app/)
- 포매터: Prettier
- 린터: ESLint (Expo 기본 설정)
- 경로 별칭: `@/` → `app/src/`

### 공통 규칙
- 함수/변수: snake_case (Python), camelCase (TS)
- 컴포넌트: PascalCase (TS)
- 상수: UPPER_SNAKE_CASE
- 파일명: 화면은 W코드 기준 (예: `WA01Login.tsx`, W코드 목록은 CLAUDE.md 섹션 9 참고), 나머지 kebab-case

### 자동 강제

> ruff가 포매팅(black 호환)과 import 정렬(isort 호환)을 모두 내장하므로 ruff 단일 도구로 통합합니다.
> 전체 설정은 `.pre-commit-config.yaml` 참조.

```yaml
# .pre-commit-config.yaml (핵심 부분)
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4
    hooks:
      - id: ruff          # 린트 + import 정렬
        args: [--fix]
        files: ^server/
      - id: ruff-format   # 포매팅 (black 호환)
        files: ^server/
```
- 첫 설정 시 `pre-commit install` 실행 (섹션 14 step 4)
- CI에서도 `ruff check` / `ruff format --check` 실행 → 실패 시 머지 차단
- 프론트엔드 lint/format CI는 `test-app` job 추가 시 포함 예정

---

## 16. 테스트 전략

### 백엔드 필수 테스트 (PR 머지 조건)
| 영역 | 테스트 대상 | 최소 커버리지 |
|---|---|---|
| 중량 계산 엔진 | `load_calc.py` 모든 equipment.category | 100% |
| 1RM 추정 | Epley 공식 경계값 (0, 음수, 극대값) | 100% |
| Progressive Overload | 트리거 조건, 증가량, max_stack 초과, sets 한계 | 100% |
| RAG 파이프라인 | 아래 시나리오 목록 참조 | 시나리오별 |
| 인증 | 아래 시나리오 목록 참조 | 시나리오별 |

#### RAG 주요 테스트 시나리오
- 한→영 번역 성공 후 ChromaDB 검색 → 결과 반환
- 번역 실패 시 원문 직접 검색 fallback 동작
- ChromaDB 검색 결과 0건일 때 응답 처리
- threshold(0.70) 미만 결과만 있을 때 처리
- LLM API 호출 실패 시 에러 응답 (mock 사용)

#### 인증 주요 테스트 시나리오
- 로그인 성공 → 토큰 발급
- 잘못된 비밀번호 → 401
- 로그인 5회 실패 → 계정 15분 잠금
- 토큰 만료 → refresh 성공
- Refresh Token Rotation + Grace Period 10초
- 폐기된 refresh token 사용 → family revoke

### 프론트엔드 테스트
- 프레임워크: Jest + React Native Testing Library
- 테스트 대상:
  - 핵심 컴포넌트 렌더링 (루틴 카드, 운동 기록 폼)
  - Zustand 스토어 상태 변경 로직
  - API 호출 mock 및 에러 처리
- 실행: `cd app && npm test`

### 테스트 실행
```bash
# 백엔드 전체 테스트
cd server && pytest tests/ -v

# 특정 모듈
pytest tests/test_load_calc.py -v

# 커버리지 리포트
pytest tests/ --cov=app --cov-report=html

# 프론트엔드 테스트
cd app && npm test

# 프론트엔드 커버리지
cd app && npm test -- --coverage
```

### 테스트 파일 네이밍
- 백엔드: `server/tests/test_{모듈명}.py`, 픽스처: `server/tests/conftest.py`
- 프론트: `app/src/**/__tests__/{컴포넌트명}.test.tsx`

---

## 17. CI/CD 파이프라인

### PR 자동 테스트 (`.github/workflows/test.yml`)
- **트리거**: `develop`, `main` 대상 PR 생성/업데이트 시
- **Status Check 이름**: `test-server` (브랜치 보호 규칙에서 참조)
- **실행 내용**:
  1. PostgreSQL 서비스 컨테이너 기동 (CI 전용)
  2. `pip install -r server/requirements.txt`
  3. `ruff check server/` — 린트 실패 시 즉시 중단
  4. `pytest server/tests/ -v --tb=short` — 테스트 실행
- **환경변수**: CI 서비스 컨테이너에서 자동 구성 (GitHub Secrets 불필요)

### 월간 논문 파이프라인 (`.github/workflows/mlops.yml`)
- **트리거**: 매월 1일 오전 11시(KST) cron + 수동 dispatch
- **실행 내용**: 논문 크롤링 → 청킹 → 임베딩 → ChromaDB upsert
- **주의**: `initial_ingest.py`(일회성)가 아닌 **증분 수집 스크립트**를 실행해야 함

### CI 실패 시 대응
- PR에 실패 로그 자동 코멘트 → 작성자가 수정 후 재push
- CI 통과 없이 머지 불가 (브랜치 보호 규칙으로 강제)

---

## 18. 배포 (AWS)

### 배포 흐름
```
develop → main PR 승인 → main 머지 → AWS 배포 → 헬스체크
```

### AWS 인프라 구성
| 서비스 | 용도 | 비고 |
|---|---|---|
| EC2 또는 ECS Fargate | FastAPI 서버 | Docker 이미지 배포 |
| RDS PostgreSQL 또는 Supabase | 관계형 DB | 프로덕션 DB |
| EBS / EFS | ChromaDB 데이터 | `/chroma-data` 영구 스토리지 |
| ECR | Docker 이미지 레지스트리 | CI에서 빌드 후 push |
| ALB | 로드 밸런서 | HTTPS 종단, 헬스체크 |

### 배포 체크리스트
1. `develop` → `main` PR 생성 및 승인 (리뷰어 1명)
2. CI 테스트 통과 확인
3. Docker 이미지 빌드 → ECR push
4. DB 마이그레이션 확인 (아래 참조)
5. ECS 서비스 업데이트 또는 EC2 배포
6. **필수**: ChromaDB 스토리지(EBS/EFS) 마운트 확인
7. 헬스체크: `GET /health` 200 응답 확인
8. 주요 기능 수동 확인 (루틴 생성, 챗봇 응답)

### DB 마이그레이션 (프로덕션)
- ECS: Task Definition의 `entryPoint`에 `alembic upgrade head` 포함, 또는 별도 migration task 실행
- EC2: SSH 접속 후 `alembic upgrade head` 수동 실행
- **로컬 DB(Docker postgres)와 프로덕션(RDS/Supabase)의 `DATABASE_URL`이 다름** — 혼동 주의
- 마이그레이션 롤백: `alembic downgrade -1` (직전 버전)

### ChromaDB 초기 데이터
- 첫 배포 시 ChromaDB가 비어 있으면 RAG가 작동하지 않음
- `mlops/scripts/initial_ingest.py`로 초기 논문 데이터 적재 필요
- 이후 월간 cron으로 증분 수집

### 환경변수 (AWS)
- ECS: Task Definition의 environment 또는 AWS Secrets Manager 사용
- EC2: `.env` 파일 또는 AWS Systems Manager Parameter Store 사용
- `ENV=production` 필수
- `CHROMA_PERSIST_PATH=/chroma-data` 필수
- 프로덕션 `/docs` (Swagger) 비활성화 또는 Security Group으로 IP 제한

### 롤백
- ECS: 이전 Task Definition revision으로 서비스 업데이트
- EC2: 이전 Docker 이미지 태그로 재배포
- DB 마이그레이션 롤백은 별도로 `alembic downgrade -1` 실행 필요

### 장애 알림 (권장)
- CloudWatch Alarms → SNS → Discord/Slack 채널로 배포 성공/실패 알림 설정
- ALB 헬스체크 실패 시 자동 알림

---

## 19. 에러 핸들링

### 응답 구조
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

### 에러 코드 매핑
| 코드 | HTTP | 용도 |
|---|---|---|
| VALIDATION_ERROR | 400 | 입력 검증 실패 |
| UNAUTHORIZED | 401 | 인증 실패/토큰 만료 |
| FORBIDDEN | 403 | 권한 부족 |
| NOT_FOUND | 404 | 리소스 미존재 |
| CONFLICT | 409 | 중복/상태 충돌 (예: 이미 등록된 이메일) |
| RATE_LIMITED | 429 | 요청 제한 초과 |
| INTERNAL_ERROR | 500 | 서버 내부 오류 |

### 구현 위치
| 파일 | 역할 |
|---|---|
| `server/app/core/exceptions.py` | AppError 기본 클래스 + 에러 카테고리별 서브클래스 |
| `server/app/core/exception_handlers.py` | 전역 핸들러 (`app.add_exception_handler`로 등록) |
| `server/app/core/middleware.py` | request_id 생성 미들웨어 (UUID → `request.state.request_id`) |

### 프로젝트 고유 에러 시나리오
| 시나리오 | 에러 코드 | 대응 |
|---|---|---|
| ChromaDB 연결 실패 | INTERNAL_ERROR | 로그 기록 + 사용자에게 "잠시 후 재시도" 응답 |
| LLM API 할당량 초과 | RATE_LIMITED | 대체 모델(GPT-4o-mini ↔ Gemini) 자동 전환 |
| 도르래 비율 범위 초과 (0 이하, 10 초과) | VALIDATION_ERROR | 기구 데이터 확인 요청 |
| SSE 스트리밍 중 연결 끊김 | — | `event_id` 기반 재연결, 마지막 이벤트부터 재전송 |
| Supabase 연결 타임아웃 | INTERNAL_ERROR | 재시도 3회 후 실패 응답 |

### 프로덕션 금지 노출 항목
- 스택 트레이스, SQL 쿼리, 파일 경로, API 키, DB 연결 문자열

---

## 20. 모니터링 (권장)

### 최소 모니터링
- AWS CloudWatch: CPU, Memory, Request count 확인
- `/health` 엔드포인트: 주기적 ping (UptimeRobot 등 무료 서비스)

### 로깅 규칙
- 모든 에러 로그에 `request_id`, `user_id`, `endpoint` 포함
- `print()` 대신 `logging` 모듈 사용
- 프로덕션 로그 레벨: `WARNING` 이상
