# 배포 가이드 (AWS)

## 배포 흐름
```
develop → main PR 승인 → main 머지 → AWS 배포 → 헬스체크
```

## AWS 인프라 구성
| 서비스 | 용도 | 비고 |
|---|---|---|
| ECS Fargate | FastAPI 서버 | Docker 이미지 배포 |
| Supabase (PostgreSQL 17.6) | 관계형 DB | 프로덕션 DB (asyncpg, `DATABASE_URL` via Secrets Manager). 로컬·CI는 `postgres:15` 컨테이너 사용 — 버전 차이 주의 |
| EFS | ChromaDB 데이터 | `/chroma-data` 영구 스토리지 (ECS Fargate는 EBS 미지원) |
| ECR | Docker 이미지 레지스트리 | CI에서 빌드 후 push |
| ALB | 로드 밸런서 | Listener 443 HTTPS(TLS 1.3) + 80 → 443 redirect, 헬스체크 |
| Route 53 | DNS | `scifit-sync.com` apex + www A 레코드 (ALB alias) |
| ACM | TLS 인증서 | `scifit-sync.com` + `www.scifit-sync.com` (자동 갱신, ap-northeast-2) |
| Secrets Manager | DATABASE_URL 등 시크릿 | ECS Task Def `secrets` 참조 |

## 프로덕션 endpoint

| 용도 | URL |
|---|---|
| **공식 API Base URL** | `https://scifit-sync.com/api/v1` |
| 헬스체크 | `https://scifit-sync.com/api/v1/health` |
| 앱 환경변수 | `EXPO_PUBLIC_API_URL=https://scifit-sync.com` |
| ALB 직접 DNS (디버그용) | `scifit-sync-alb-1884701506.ap-northeast-2.elb.amazonaws.com` |

HTTP는 ALB Listener 80에서 자동 HTTPS 301 redirect. 모바일 ATS(iOS) / Cleartext Traffic(Android) 정책 통과.

## 배포 파이프라인 (자동 — `.github/workflows/deploy.yml`)
`main` push 또는 workflow_dispatch(수동 재배포/일회성 reseed) 시 자동 실행:

1. Docker 이미지 빌드 → ECR push (`{커밋 SHA}` + `latest` 태그)
2. 현재 Task Definition 다운로드 → 새 이미지로 갱신 → 새 revision 등록
3. **[조건부] prod DB 백업**: `PROD_DATABASE_URL` + `BACKUP_S3_URI` secret 설정 시 `pg_dump` → gzip → S3 업로드 (100바이트 초과 검증, 미달 시 배포 중단 / 미설정이면 경고 후 skip)
4. one-off Fargate 태스크로 `alembic upgrade head` 실행 — **clean_slate 가드**: 사용자 데이터가 존재하고 `ALLOW_CLEAN_SLATE_WIPE` 미설정이면 마이그레이션 중단 (workflow_dispatch의 `allow_clean_slate_wipe=true`일 때만 해제)
5. `update-service --desired-count 1` — 콘솔에서 desiredCount가 변경됐어도 매 배포 시 1로 강제 복구 (ChromaDB 단일 인스턴스 제약)
6. `aws ecs wait services-stable` 대기 후 완료

배포 후 확인: `GET /api/v1/health` 200 응답 + 주요 기능 수동 확인 (루틴 생성, 챗봇 응답)

## DB 마이그레이션 (프로덕션)
- ECS: Task Definition의 `entryPoint`에 `alembic upgrade head` 포함, 또는 별도 migration task 실행
- **로컬 DB(Docker postgres)와 프로덕션(Supabase)의 `DATABASE_URL`이 다름** — 혼동 주의
- 마이그레이션 롤백: `alembic downgrade -1` (직전 버전)

## ChromaDB 초기 데이터
- 첫 배포 시 ChromaDB가 비어 있으면 RAG가 작동하지 않음
- `mlops/scripts/initial_ingest.py`로 초기 논문 데이터 적재 필요 (최초 1회)
- 이후 `mlops/scripts/monthly_ingest.py`로 월간 증분 수집 (GitHub Actions cron)

## 환경변수 (AWS)
- ECS: Task Definition의 environment 또는 AWS Secrets Manager 사용
- `ENV=production` 필수
- `CHROMA_PERSIST_PATH=/chroma-data` 필수
- 프로덕션 `/docs` (Swagger) 비활성화 또는 Security Group으로 IP 제한

## ChromaDB 단일 인스턴스 제약
- ChromaDB `PersistentClient`는 **단일 프로세스 전용** — 동시 쓰기 미지원
- ECS Fargate Task 수를 2개 이상으로 스케일링하면 데이터 충돌 발생
- **반드시 단일 인스턴스(Task count=1)로 운영**, 수평 확장 필요 시 별도 벡터 DB(Qdrant, Weaviate 등) 전환 검토

## ALB 헬스체크 (현재 설정 — 원복 주의)
대량 RAG 적재 시 단일 태스크(0.5 vCPU)의 이벤트 루프가 순간 점유되어, 콜드스타트/적재 중 헬스체크가 타임아웃 → 태스크가 반복 kill되는 현상이 있었다. 이를 완화하려 **의도적으로** 다음 비표준 설정을 적용 중:

- 타깃그룹 `scifit-sync-tg`: HealthCheck **timeout 20s** (기본 10s 아님), **unhealthy threshold 5** (기본 2 아님)
- ECS 서비스 `healthCheckGracePeriodSeconds` **300** (콜드스타트 보호)

⚠️ **기본값(10s / 2)으로 "원복"하면 적재 중 crash loop가 재발하므로 함부로 되돌리지 말 것.** 코드 측 `admin.py` ChromaDB 호출 `asyncio.to_thread` 오프로드는 적용됨. 추가 근본개선(startup pre-warm / CPU 증설)이 끝나기 전까지 위 설정 유지.

## 롤백
- ECS: 이전 Task Definition revision으로 서비스 업데이트
- DB 마이그레이션 롤백은 별도로 `alembic downgrade -1` 실행 필요

## 장애 알림 (권장)
- CloudWatch Alarms → SNS → Discord/Slack 채널로 배포 성공/실패 알림 설정
- ALB 헬스체크 실패 시 자동 알림

## CI/CD 파이프라인

### PR 자동 테스트 (`.github/workflows/test.yml`)
- **트리거**: `develop`, `main` 대상 PR 생성/업데이트 시
- **Status Check 이름**: `test-server` (브랜치 보호 규칙에서 참조)
- **3-job 구조** (`lint` 통과 후 두 test job 병렬 실행):
  1. `lint` — `ruff check server/ mlops/` + `ruff format --check server/ mlops/`
  2. `test-server` — `postgres:15-alpine` 서비스 컨테이너 기동 → `alembic upgrade head` 마이그레이션 → `pytest server/tests/ --cov=app --cov-report=term-missing`
  3. `test-mlops` — `pytest mlops/tests/ -m "not integration"` (외부 API 실호출 테스트 제외)
- **coverage는 측정·보고만** 수행 (fail-under 없음 — 커버리지 수치로 머지가 차단되지 않음)
- **환경변수**: CI 서비스 컨테이너에서 자동 구성 (GitHub Secrets 불필요)

### 월간 논문 파이프라인 (`.github/workflows/mlops.yml`)
- **트리거**: 매월 1일 오전 11시(KST) cron + 수동 dispatch
- **실행 내용**: 논문 크롤링 → 청킹 → 임베딩 → ChromaDB upsert
- **주의**: `initial_ingest.py`(일회성)가 아닌 `monthly_ingest.py`(증분 수집)를 실행해야 함

## 모니터링 (권장)

### 최소 모니터링
- AWS CloudWatch: CPU, Memory, Request count 확인
- `/api/v1/health` 엔드포인트: 주기적 ping (UptimeRobot 등 무료 서비스)

### 로깅 규칙
- 모든 에러 로그에 `request_id`, `user_id`, `endpoint` 포함
- `print()` 대신 `logging` 모듈 사용
- 프로덕션 로그 레벨: `WARNING` 이상
