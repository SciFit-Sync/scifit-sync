# SciFit-Sync

[![CI](https://github.com/SciFit-Sync/scifiit-sync/actions/workflows/test.yml/badge.svg)](https://github.com/SciFit-Sync/scifiit-sync/actions/workflows/test.yml)
[![MLOps](https://github.com/SciFit-Sync/scifiit-sync/actions/workflows/mlops.yml/badge.svg)](https://github.com/SciFit-Sync/scifiit-sync/actions/workflows/mlops.yml)

> 스포츠 과학 논문 RAG 기반 개인 맞춤형 운동 루틴 생성 앱

**"당신의 운동에 근거를 더하다"**

---

## 프로젝트 개요

기존 운동 앱들은 루틴 추천 시 과학적 근거 없이 일반적인 가이드라인만 제공합니다.
SciFit-Sync는 **PubMed 스포츠 과학 논문을 RAG 파이프라인**으로 분석하여,
사용자의 신체 정보·운동 목표·보유 기구에 맞는 **근거 기반 운동 루틴**을 자동 생성합니다.

| 항목 | 내용 |
|------|------|
| 과목 | 캡스톤 디자인 (2025년 1학기) |
| 개발 기간 | 2025.03 ~ 2025.06 (16주) |

### 팀 구성

총 6명의 팀원이 각자의 전문 분야를 담당하며, 파트 간의 유기적인 협업을 통해 RAG 기반 맞춤형 운동 루틴 파이프라인을 구축하고 있습니다.

| 역할 | 담당 |
|------|------|
| **Team Lead** · MLOps Lead & System Architect | 시스템 아키텍처 설계, 백엔드 초기 프레임워크 구현, MLOps 파이프라인 전체(크롤링·청킹·임베딩·적재), GitHub CI/CD 및 협업 인프라, 설계 문서 총괄 |
| **AI/Data Engineer** | RAG 파이프라인, LLM 프롬프트 엔지니어링(Gemini), 논문 데이터 분석 |
| **AI/Data Engineer** · Cross-functional | 데이터 전처리, 임베딩 모델 고도화, MLOps 파이프라인 로직 지원 |
| **Backend Engineer** | 비즈니스 로직 API(FastAPI), 루틴·운동 기록 도메인, SSE 스트리밍 |
| **Backend Engineer** | 인증(JWT/OAuth), 헬스장·기구 도메인, 카카오 API 연동, 에러 핸들링 |
| **Frontend Engineer** | React Native(Expo), 상태 관리(Zustand), 서버 동기화(TanStack Query) |

---

## 핵심 기능

| 기능 | 설명 |
|------|------|
| **논문 기반 루틴 생성** | PubMed 스포츠 과학 논문을 RAG 파이프라인으로 검색·분석하여 근거 있는 운동 루틴을 자동 생성하고, 참고 논문 출처 카드를 첨부 |
| **도르래 비율 보정** | 케이블 머신 등 도르래 기반 기구의 실효 부하를 자동 계산하여 기구 간 정확한 중량 비교 지원 |
| **AI 챗봇** | 운동 관련 질문에 관련 논문을 검색한 뒤, 논문 출처 카드를 첨부하여 근거 기반 답변 제공 |
| **Progressive Overload** | 운동 기록을 분석하여 목표 달성 시 자동 중량 증가 제안, 기구 한계 도달 시 대안 안내 |

---

## 시스템 아키텍처

```
[사용자 - Expo App]
    │  HTTPS / SSE (event_id 기반 재연결)
    ▼
[FastAPI 서버 (Python 3.11+)]
    ├── Auth Service ─── JWT + Refresh Token Rotation (Grace Period 10s)
    ├── Routine Service ── 중량 계산 엔진 (도르래 비율 보정, 1RM Epley)
    ├── Chat Service ──── RAG Pipeline
    │                       ├── 한→영 번역 (Gemini) + fallback 원문 검색
    │                       ├── ChromaDB 벡터 검색 (top_k=10, threshold ≥ 0.70)
    │                       └── LLM 응답 생성 (Gemini 1.5 Flash → GPT-4o-mini fallback)
    └── Equipment Service ── 카카오 로컬 API 프록시

[PostgreSQL — Supabase]    [ChromaDB — 인프로세스 PersistentClient]

[GitHub Actions Cron] ── 월 1회 논문 크롤링 → 청킹 → 임베딩 → ChromaDB upsert
```

### RAG 파이프라인

```
1. 수집     PubMed/PMC에서 스포츠 과학 논문 크롤링 (월 1회, GitHub Actions Cron)
2. 전처리   Section-Aware 청킹 (300~512 토큰, overlap 50)
3. 임베딩   BAAI/bge-large-en-v1.5 → 1024차원 벡터 변환
4. 저장     ChromaDB에 메타데이터와 함께 저장
5. 검색     사용자 질의 한→영 번역 → 임베딩 → 코사인 유사도 Top-10 (threshold ≥ 0.70)
6. 생성     검색된 논문 컨텍스트 + 프로필 + 프롬프트 → LLM 루틴 생성 (SSE 스트리밍)
```

---

## 기술 스택

| 영역 | 기술 | 비고 |
|---|---|---|
| 모바일 | React Native + Expo (Managed) | Expo Go 개발, EAS Build 배포 |
| 상태 관리 | TanStack Query + Zustand | |
| 백엔드 | FastAPI | Python 3.11+, Pydantic v2 |
| ORM | SQLAlchemy 2.0 async | asyncpg 드라이버 |
| DB | PostgreSQL (Supabase) | Alembic 마이그레이션 |
| Vector DB | ChromaDB 인프로세스 | PersistentClient, `/chroma-data` 볼륨 |
| LLM | Gemini 1.5 Flash → GPT-4o-mini | 환경변수로 전환, 자동 fallback |
| 임베딩 | BAAI/bge-large-en-v1.5 | 1024차원 |
| 배포 | AWS (EC2/ECS) | Docker 이미지, ALB + HTTPS |
| CI/CD | GitHub Actions | PR 테스트 자동화 + 월간 논문 파이프라인 |
| 코드 품질 | ruff (Python) / Prettier + ESLint (TS) | CI에서 자동 검사 |
| 테스트 | pytest (백엔드) / Jest + RNTL (프론트) | |

---

## 로컬 개발 환경

### 사전 요구사항

- Python 3.11+
- Node.js 18+ / npm 9+
- Docker Desktop
- Expo Go 앱 (모바일 테스트, iOS/Android)

### 설치 및 실행

```bash
# 1. 리포 클론
git clone https://github.com/SciFit-Sync/scifiit-sync.git
cd scifiit-sync
git checkout develop

# 2. 환경변수 설정
cp server/.env.example server/.env
cp app/.env.example app/.env
# → .env 파일에 실제 키 입력 (아래 환경변수 표 참고)

# 3. Docker로 서버 + DB 실행
docker compose up

# 4. DB 마이그레이션 (별도 터미널)
docker compose exec server alembic upgrade head

# 5. 모바일 앱 실행 (별도 터미널)
cd app && npm install && npx expo start
```

> 상세 환경 셋업: [`docs/guides/environment-setup.md`](docs/guides/environment-setup.md)

### 주요 환경변수

| 변수명 | 설명 | 필수 | 획득처 |
|--------|------|:----:|--------|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | Y | Supabase 대시보드 |
| `JWT_SECRET_KEY` | JWT 서명 키 | Y | `openssl rand -hex 32` |
| `GEMINI_API_KEY` | Gemini API 키 | Y | Google AI Studio |
| `KAKAO_REST_API_KEY` | 카카오 로컬 API 키 | Y | Kakao Developers |
| `OPENAI_API_KEY` | GPT-4o-mini 폴백 키 | N | OpenAI 대시보드 |
| `API_BASE_URL` (앱) | 서버 URL | Y | 로컬: `http://localhost:8000` |

> 전체 환경변수 목록: [`server/.env.example`](server/.env.example)

---

## API 문서

서버 실행 후 자동 생성:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

> 프로덕션에서는 `/docs` 비활성화 또는 IP 제한  
> 전체 API 명세 (50개): [`docs/spec/api-endpoints.md`](docs/spec/api-endpoints.md)

---

## 테스트

```bash
# 백엔드 테스트
cd server && pytest tests/ -v

# 커버리지 리포트
pytest tests/ --cov=app --cov-report=html

# 프론트엔드 테스트
cd app && npm test
```

> 필수 100% 커버리지: 중량 계산, 1RM, Progressive Overload  
> 테스트 전략 상세: [`docs/guides/testing-strategy.md`](docs/guides/testing-strategy.md)

---

## 프로젝트 구조

```
scifiit-sync/
├── app/                  # React Native + Expo
│   ├── src/
│   │   ├── screens/          # 화면 (W코드 기준, 예: WA01Login.tsx)
│   │   ├── components/       # 공통 컴포넌트
│   │   ├── stores/           # Zustand 스토어
│   │   ├── services/         # API 호출 (TanStack Query)
│   │   └── constants/        # 디자인 토큰, 상수
│   ├── app.json              # Expo 설정
│   ├── package.json
│   └── tsconfig.json
├── server/               # FastAPI 백엔드
│   ├── app/
│   │   ├── api/v1/           # 엔드포인트 (도메인별 라우터)
│   │   ├── models/           # SQLAlchemy 모델
│   │   ├── schemas/          # Pydantic 스키마
│   │   ├── services/         # 비즈니스 로직 (RAG, 중량 계산, PO)
│   │   └── core/             # 설정, 인증, 에러 핸들링, 미들웨어
│   ├── alembic/              # DB 마이그레이션
│   ├── tests/                # pytest 테스트
│   ├── Dockerfile
│   └── requirements.txt
├── mlops/                # 논문 파이프라인
│   ├── pipeline/             # 크롤러, 청킹, 임베딩, upsert
│   ├── scripts/              # 실행 스크립트 (initial/monthly ingest)
│   └── requirements.txt
├── docs/                 # 문서
│   ├── spec/                 # API 명세, DB 스키마, 화면 목록
│   └── guides/               # 셋업, 배포, 테스트, 에러 핸들링
├── .github/
│   ├── workflows/            # CI (test.yml, mlops.yml)
│   ├── ISSUE_TEMPLATE/       # 이슈 템플릿
│   └── pull_request_template.md
├── CLAUDE.md             # 프로젝트 설계 기준 (내부용)
├── docker-compose.yml
└── .gitignore
```

---

## 브랜치 전략

```
main      ← 배포 브랜치 (PR only, 리뷰어 1명 승인)
develop   ← 개발 통합 (PR only)
feature/{이름}/{기능}     ← 기능 개발
fix/{이름}/{버그}         ← 버그 수정
```

## 커밋 컨벤션

| 타입 | 용도 |
|------|------|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 (기능 변경 없음) |
| `docs` | 문서 변경 |
| `test` | 테스트 추가/수정 |
| `style` | 코드 포매팅 (동작 변경 없음) |
| `chore` | 기타 (의존성, 설정 등) |
| `ci` | CI/CD 변경 |

---

## CI/CD

| 워크플로우 | 트리거 | 내용 |
|------------|--------|------|
| **test.yml** | `develop`, `main` 대상 PR | ruff lint/format 검사 → pytest 실행 |
| **mlops.yml** | 매월 1일 11시(KST) + 수동 | 논문 크롤링 → 청킹 → 임베딩 → ChromaDB upsert |

---

## 설계 문서

| 문서 | 링크 |
|------|------|
| 마스터 설계서 | [Notion](https://www.notion.so/Scifit-Sync-33daebb23ee080f1b3aef1f7c8b416b1) |
| 와이어프레임 (23개 화면) | [Figma](https://www.figma.com/design/lowVkeYctKKWbXx7AYIa6V/) |
| 프로젝트 설계 기준 (내부) | [`CLAUDE.md`](CLAUDE.md) |
| API 명세 (50개 엔드포인트) | [`docs/spec/api-endpoints.md`](docs/spec/api-endpoints.md) |
| DB 스키마 (29개 테이블) | [`docs/spec/database-schema.md`](docs/spec/database-schema.md) |
| 화면 목록 (23개) | [`docs/spec/screens.md`](docs/spec/screens.md) |
| 환경 셋업 가이드 | [`docs/guides/environment-setup.md`](docs/guides/environment-setup.md) |
| 배포 + CI/CD | [`docs/guides/deployment.md`](docs/guides/deployment.md) |
| 에러 핸들링 | [`docs/guides/error-handling.md`](docs/guides/error-handling.md) |
| 테스트 전략 | [`docs/guides/testing-strategy.md`](docs/guides/testing-strategy.md) |

---

## 설계 결정 및 한계점

| 항목 | 설명 |
|------|------|
| **청킹 토크나이저** | 현재 파이프라인은 구현 편의성과 속도를 고려해 청킹 시 `tiktoken`(cl100k_base)을 사용 중이며, 추후 BGE 모델 전용 토크나이저로 고도화하여 토큰 수 산정 오차를 줄일 예정 |
| **Token Refresh 주체** | "SSE 연결 전 잔여 5분 미만 시 사전 refresh" 정책은 서버가 아닌 클라이언트(React Native)의 API 인터셉터에서 수행하는 Client-side 정책 |
| **MLOps 테스트 개수** | crawler 9개, chunker 14개 (총 23개). 설계서 일부에 crawler 14/chunker 9로 오기재된 부분이 있으며, 실제 구현 기준으로 정상 통과(Pass) |

---

## 데모

> 개발 진행에 따라 업데이트 예정

| 홈 화면 | 루틴 생성 | 챗봇 | 운동 기록 |
|---------|----------|------|----------|
| 준비 중 | 준비 중 | 준비 중 | 준비 중 |

---

## 라이선스

라이선스 미정 — 캡스톤 프로젝트 완료 후 결정 예정
