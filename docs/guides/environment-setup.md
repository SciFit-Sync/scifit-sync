# 환경 셋업 가이드 (신규 팀원)

## 사전 요구사항
- Python 3.11+
- Node.js 18+ / npm 9+
- Docker Desktop (Windows: WSL2 백엔드 활성화 필수)
- Expo Go 앱 (모바일 테스트용, iOS/Android)
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

## 환경변수 전체 목록

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

## 시크릿 공유 정책
- 시크릿은 **팀 공유 1Password** 또는 **암호화된 채널**로만 공유
- Notion 페이지에 API 키 직접 기재 금지
- 각자 개인 키 발급 권장 (Gemini, Kakao 등)

## 플랫폼별 주의사항
| 환경 | 주의 |
|---|---|
| Windows (WSL2) | Docker Desktop WSL2 Integration 활성화 필수. Expo는 WSL 내부가 아닌 PowerShell에서 실행 권장 |
| Mac (Apple Silicon) | `pip install` 시 일부 패키지 arm64 빌드 이슈 가능 → `--platform` 플래그 또는 Rosetta 사용 |
| Linux | Docker는 `sudo` 없이 사용하도록 그룹 추가: `sudo usermod -aG docker $USER` |
