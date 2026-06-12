# 환경 셋업 가이드 (신규 팀원)

## 사전 요구사항
- Python 3.11+
- Node.js 20+ / npm 9+ (Expo SDK 54 요구)
- Docker Desktop (Windows: WSL2 백엔드 활성화 필수)
- expo-dev-client 개발 빌드 (모바일 테스트용 — 네이티브 모듈 포함으로 **Expo Go 사용 불가**. Xcode/Android Studio 로컬 빌드 또는 EAS Build로 개발 빌드 설치 필요)
- Git

## Docker 서비스 구성
| 서비스 | 이미지 | 포트 | 비고 |
|---|---|---|---|
| server | `./server` (빌드) | 8000 | FastAPI |
| db | `postgres:15-alpine` | 5432 | 로컬 개발 DB |

> ChromaDB는 FastAPI 서버 내 인프로세스(`PersistentClient`)로 동작하며, `/chroma-data` 볼륨에 데이터 저장

## 첫 설정

```bash
# 1. 리포 클론
git clone https://github.com/SciFit-Sync/scifit-sync.git
cd scifit-sync
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
# → EXPO_PUBLIC_API_URL=http://10.0.2.2:8000 (Android 에뮬레이터 기본값)
# → 프로덕션 빌드(EAS Build): EXPO_PUBLIC_API_URL=https://scifit-sync.com
```

```bash
# 4. Docker로 실행
docker compose up
```

```bash
# 5. DB 마이그레이션
docker compose exec server alembic upgrade head
```

```bash
# 6. 앱 실행 (별도 터미널)
cd app && npm install && npx expo start
```

## 주요 환경변수

> 전체 목록은 `server/.env.example` 참조.

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
| `EXPO_PUBLIC_API_URL` (앱) | 서버 API URL | Y | 프로덕션: `https://scifit-sync.com` / 로컬: `http://localhost:8000` |

## 시크릿 공유 정책
- 시크릿은 **팀 공유 1Password** 또는 **암호화된 채널**로만 공유
- Notion 페이지에 API 키 직접 기재 금지
- 각자 개인 키 발급 권장 (Gemini, Kakao 등)

## GitHub Actions Secrets 설정

GitHub 레포 > Settings > Secrets and variables > Actions 에서 설정:

| Secret 이름 | 용도 | 사용 워크플로우 |
|---|---|---|
| `API_BASE_URL` | 프로덕션 서버 URL (예: `https://scifit-sync.com`) | `mlops.yml` |
| `ADMIN_API_TOKEN` | 서버 admin API 인증 토큰 | `mlops.yml` |
| `NCBI_API_KEY` | NCBI(PubMed) API 키 | `mlops.yml` |
| `OPENALEX_MAILTO` | OpenAlex polite pool 이메일 | `mlops.yml` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | 배포용 IAM 사용자 키 | `deploy.yml` |
| `AWS_REGION` | 리전 (예: `ap-northeast-2`) | `deploy.yml` |
| `ECR_REPOSITORY` | ECR 저장소 이름 | `deploy.yml` |
| `ECS_CLUSTER` / `ECS_SERVICE` / `ECS_TASK_DEFINITION` / `CONTAINER_NAME` | ECS 배포 대상 식별자 | `deploy.yml` |
| `ECS_SUBNET_IDS` / `ECS_SG_IDS` | 마이그레이션 one-off 태스크용 서브넷/보안 그룹 | `deploy.yml` |
| `PROD_DATABASE_URL` / `BACKUP_S3_URI` | 마이그레이션 전 pg_dump → S3 백업 (두 secret 설정 시 활성화) | `deploy.yml` |

## 플랫폼별 주의사항
| 환경 | 주의 |
|---|---|
| Windows (WSL2) | Docker Desktop WSL2 Integration 활성화 필수. Expo는 WSL 내부가 아닌 PowerShell에서 실행 권장 |
| Mac (Apple Silicon) | `pip install` 시 일부 패키지 arm64 빌드 이슈 가능 → `--platform` 플래그 또는 Rosetta 사용 |
| Linux | Docker는 `sudo` 없이 사용하도록 그룹 추가: `sudo usermod -aG docker $USER` |
