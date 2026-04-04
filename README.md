# SciFit-Sync

> 스포츠 과학 논문 RAG 기반 개인 맞춤형 운동 루틴 생성 앱

**"당신의 운동에 근거를 더하다"**

## 프로젝트 개요

기존 운동 앱들은 루틴 추천 시 과학적 근거 없이 일반적인 가이드라인만 제공합니다.
SciFit-Sync는 **PubMed 스포츠 과학 논문을 RAG 파이프라인**으로 분석하여,
사용자의 신체 정보·운동 목표·보유 기구에 맞는 **근거 기반 운동 루틴**을 자동 생성합니다.

| 항목 | 내용 |
|------|------|
| 과목 | 캡스톤 디자인 (2025년 1학기) |
| 학교 | [TODO] OO대학교 소프트웨어학과 |
| 지도교수 | [TODO] OOO 교수님 |
| 개발 기간 | 2025.03 ~ 2025.06 (16주) |

### 팀 구성

| 이름 | 역할 | 담당 |
|------|------|------|
| [TODO] | PM / Backend | FastAPI, DB 설계, 인증 |
| [TODO] | Backend | 비즈니스 로직, 중량 계산 엔진 |
| [TODO] | Frontend | React Native, UI/UX |
| [TODO] | Frontend | 화면 구현, 상태 관리 |
| [TODO] | ML / Data | RAG 파이프라인, 논문 임베딩 |
| [TODO] | Infra / QA | CI/CD, 배포, 테스트 |

## 핵심 기능

- **논문 기반 루틴 생성** — PubMed 스포츠 과학 논문을 RAG 파이프라인으로 검색·분석하여 근거 있는 운동 루틴을 자동 생성하고, 참고 논문 출처 카드를 첨부
- **도르래 비율 보정** — 케이블 머신 등 도르래 기반 기구는 도르래 배치에 따라 실제 부하가 표시 중량과 다름. 기구별 도르래 비율 DB를 구축하여 실효 부하를 자동 계산하고, 기구 간 정확한 중량 비교를 지원
- **AI 챗봇** — 운동 관련 질문에 관련 논문을 검색한 뒤, 논문 출처 카드를 첨부하여 근거 기반 답변 제공
- **Progressive Overload** — 운동 기록을 분석하여 목표 달성 시 자동 중량 증가 제안, 기구 한계 도달 시 대안 안내

## 시스템 아키텍처

```
[사용자 - Expo App]
    │  HTTPS / SSE
    ▼
[FastAPI 서버]
    ├── Auth Service ─── JWT + Refresh Token Rotation
    ├── Routine Service ── 중량 계산 엔진 (도르래 비율 보정)
    ├── Chat Service ──── RAG Pipeline
    │                       ├── 한→영 번역 (Gemini)
    │                       ├── ChromaDB 벡터 검색 (top_k=10)
    │                       └── LLM 응답 생성
    └── Equipment Service ── 카카오 로컬 API 프록시

[PostgreSQL — Supabase]    [ChromaDB — 인프로세스]

[GitHub Actions] ── 월 1회 논문 크롤링 → 청킹 → 임베딩 → ChromaDB upsert
```

### RAG 파이프라인
1. **수집**: PubMed/PMC에서 스포츠 과학 논문 크롤링 (월 1회 자동, GitHub Actions Cron)
2. **전처리**: Section-Aware 청킹 (300~512 토큰, overlap 50)
3. **임베딩**: BAAI/bge-large-en-v1.5로 1024차원 벡터 변환
4. **저장**: ChromaDB에 메타데이터와 함께 저장
5. **검색**: 사용자 질의 한→영 번역 → 임베딩 → 코사인 유사도 Top-10 (threshold >= 0.70)
6. **생성**: 검색된 논문 컨텍스트 + 프롬프트 → LLM이 루틴 생성 (SSE 스트리밍)

## 기술 스택

| 영역 | 기술 | 버전/비고 |
|---|---|---|
| 모바일 | React Native + Expo (Managed) | Expo Go 개발, EAS Build 배포 |
| 상태 관리 | TanStack Query + Zustand | |
| 백엔드 | FastAPI | Python 3.11+ |
| ORM | SQLAlchemy 2.0 async | Pydantic v2 |
| DB | PostgreSQL (Supabase) | |
| Vector DB | ChromaDB 인프로세스 | PersistentClient |
| LLM | Gemini 1.5 Flash (1차) → GPT-4o-mini (폴백) | 환경변수로 전환 |
| 임베딩 | BAAI/bge-large-en-v1.5 | 1024차원 |
| 배포 | AWS (EC2/ECS) | Docker 이미지 배포 |
| MLOps | GitHub Actions Cron | 월 1회 자동 |
| 테스트 | pytest (백엔드) / Jest (프론트) | |

## 로컬 개발 환경

### 사전 요구사항
- Python 3.11+
- Node.js 18+
- Docker Desktop

### 설치 및 실행

```bash
# 1. 리포 클론
git clone https://github.com/SciFit-Sync/scifiit-sync.git
cd scifiit-sync
git checkout develop
```

```bash
# 2. 환경변수 설정
cp server/.env.example server/.env
cp app/.env.example app/.env
# .env 파일에 실제 키 입력 (환경변수 목록은 CLAUDE.md 섹션 14 참고)
```

```bash
# 3. Docker로 실행
docker compose up
```

```bash
# 4. DB 마이그레이션
docker compose exec server alembic upgrade head
```

```bash
# 5. 모바일 앱 실행 (별도 터미널)
cd app && npm install && npx expo start
```

### 주요 환경변수

| 변수명 | 설명 | 필수 |
|--------|------|------|
| `DATABASE_URL` | Supabase PostgreSQL 연결 문자열 | Y |
| `GEMINI_API_KEY` | Google Gemini API 키 | Y |
| `KAKAO_REST_API_KEY` | 카카오 로컬 API 키 | Y |
| `JWT_SECRET_KEY` | JWT 서명 키 | Y |
| `API_BASE_URL` (앱) | 서버 API URL (로컬: `http://localhost:8000`) | Y |

> 전체 환경변수 목록: `server/.env.example` 및 `CLAUDE.md` 섹션 14

## API 문서

서버 실행 후 자동 생성:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

> 프로덕션에서는 `/docs` 비활성화 또는 IP 제한

## 테스트

```bash
# 백엔드 테스트
cd server && pytest tests/ -v

# 백엔드 커버리지
pytest tests/ --cov=app --cov-report=html

# 프론트엔드 테스트
cd app && npm test
```

## 프로젝트 구조

```
scifiit-sync/
├── app/              # React Native + Expo
│   └── src/
│       ├── screens/      # 화면 (와이어프레임 W코드 기준)
│       ├── components/   # 공통 컴포넌트
│       ├── stores/       # Zustand 스토어
│       ├── services/     # API 호출 (TanStack Query)
│       └── constants/    # 디자인 토큰
├── server/           # FastAPI 백엔드
│   ├── app/
│   │   ├── api/v1/       # 엔드포인트 (도메인별)
│   │   ├── models/       # SQLAlchemy 모델
│   │   ├── schemas/      # Pydantic 스키마
│   │   ├── services/     # 비즈니스 로직 (RAG, 중량 계산)
│   │   └── core/         # 설정, 인증, 에러 핸들링
│   ├── alembic/          # DB 마이그레이션
│   └── tests/            # pytest 테스트
├── mlops/            # 논문 파이프라인
│   ├── pipeline/         # 크롤러, 청킹, 임베딩, upsert
│   └── scripts/          # 실행 스크립트
├── docs/             # 문서
├── CLAUDE.md         # 프로젝트 설계 기준 (내부용)
└── docker-compose.yml
```

## 브랜치 전략

```
main      ← 배포 브랜치 (PR only, 승인 1명)
develop   ← 개발 통합 (PR only)
feature/{이름}/{기능}
fix/{이름}/{버그}
```

## 커밋 컨벤션

```
feat:     새 기능
fix:      버그 수정
refactor: 리팩토링 (기능 변경 없음)
docs:     문서 변경
test:     테스트 추가/수정
style:    코드 포매팅 (동작 변경 없음)
chore:    기타 (의존성, 설정 등)
ci:       CI/CD 변경
```

## 설계 문서

- [마스터 설계서 (Notion)](https://www.notion.so/338aebb23ee081af885ecdda757047d5)
- [와이어프레임 (Figma)](https://www.figma.com/design/lowVkeYctKKWbXx7AYIa6V/)
- 프로젝트 내부 설계 기준: `CLAUDE.md`

## 데모

> 개발 진행에 따라 업데이트 예정

| 홈 화면 | 루틴 생성 | 챗봇 | 운동 기록 |
|---------|----------|------|----------|
| 준비 중 | 준비 중 | 준비 중 | 준비 중 |

## 라이선스

[TODO] 라이선스 결정 후 명시
