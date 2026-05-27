# ============================================================
# Stage 1: builder — venv 격리로 의존성 설치
# ============================================================
FROM python:3.11-slim AS builder

# native 컴파일 deps (일부 pkg가 wheel 미제공 시 빌드)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# venv 격리 — 두 RUN pip install 사이 site-packages 상태가 명시적으로 공유됨.
# (--prefix 방식은 pip 23+에서만 target prefix 인식 보장이라 venv가 더 안전.)
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /install
COPY server/requirements.txt .

# torch CPU-only wheel 명시 설치 — sentence-transformers가 default PyPI에서
# GPU 포함 torch(~2GB) 끌어오는 것 차단. ECS Fargate는 GPU 없음 (CLAUDE.md §2).
# venv 안에 먼저 설치되면 후속 sentence-transformers는 `Requirement already satisfied`로 재사용.
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.5.1

# 나머지 의존성 — --extra-index-url로 PyPI와 CPU wheel 인덱스를 함께 검색 (CPU 우선이 아닌 동시 검색).
# 이미 설치된 torch는 재설치 안 함.
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

# ============================================================
# Stage 2: runtime — 앱 실행
# ============================================================
FROM python:3.11-slim AS runtime

# torch CPU wheel 런타임 의존성 (OpenMP). torch 일부 op가 libgomp1 호출.
# python:3.11-slim(bookworm-slim)에 미포함이라 명시 설치 — 미설치 시 `import torch` fail 위험.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# venv 복사 — site-packages, bin/, lib/ 등 일관된 격리
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 앱 코드
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
