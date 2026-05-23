FROM python:3.11-slim

WORKDIR /app

# Build context는 repo root (deploy.yml과 docker-compose.yml 양쪽).
# server/ 외에 mlops/data도 컨테이너에 넣어야 Alembic seed 마이그레이션이
# CSV(equipments_seed.csv)를 읽을 수 있다.
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ /app/

# 마이그레이션이 필요한 단일 CSV만 복사 (mlops/data/ 전체 복사는 ECR 이미지 비대화 + cold start 지연).
# 향후 brand별 raw CSV 적재 시점에 명시 추가.
COPY mlops/data/equipments_seed.csv /app/mlops/data/equipments_seed.csv

# Non-root user + ChromaDB 볼륨 + 정적 파일 디렉터리 권한 설정
# - /chroma-data: EFS 마운트 대상. Access Point가 1000:1000으로 squash하지만
#   로컬 dev (docker-compose, EFS 미마운트) 시 appuser가 쓸 수 있어야 함
# - /app/static: main.py:create_app()이 mkdir(exist_ok=True)로 만들려고 시도.
#   `/app`이 root 소유라 appuser가 mkdir 실패 → PermissionError. 미리 만들고 chown.
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser \
    && mkdir -p /chroma-data /app/static \
    && chown -R appuser:appgroup /chroma-data /app/static
USER appuser

EXPOSE 8000

# /api/v1/health 엔드포인트로 컨테이너 상태 확인
# start-period: 앱 기동 대기 (ChromaDB 초기화 포함)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

# workers=1 고정: ChromaDB PersistentClient는 단일 프로세스 전용 (CLAUDE.md §15)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
