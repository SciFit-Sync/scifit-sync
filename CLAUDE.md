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
| 배포 | Railway Hobby | Volume /chroma-data 마운트 필수 |
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
- Railway 배포 시 /chroma-data 볼륨 없이 배포 → 데이터 소실
- LLM에 사용자 입력 raw 전달 → <user_query> 태그 필수
- .env 파일 커밋 → .gitignore 확인

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
