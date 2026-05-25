import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_bool(key: str, default: str = "false") -> bool:
    """ENV var를 bool로 파싱. 'true'/'1'/'yes'/'on' (대소문자 무관) 모두 True."""
    return os.getenv(key, default).strip().lower() in {"1", "true", "yes", "on"}


# PubMed
NCBI_API_KEY: str = os.getenv("NCBI_API_KEY", "")
NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_RATE_LIMIT: float = 0.34 if NCBI_API_KEY else 1.0  # 초 단위 대기

# PMC 전문 수집 retry 정책 (env로 조정 가능 — fulltext 회수율 ↔ 실행시간 trade-off)
NCBI_HTTP_MAX_RETRIES: int = int(os.getenv("NCBI_HTTP_MAX_RETRIES", "5"))
NCBI_HTTP_MAX_BACKOFF: float = float(os.getenv("NCBI_HTTP_MAX_BACKOFF", "10.0"))
NCBI_HTTP_TIMEOUT: int = int(os.getenv("NCBI_HTTP_TIMEOUT", "60"))
PMC_FULLTEXT_MAX_ATTEMPTS: int = int(os.getenv("PMC_FULLTEXT_MAX_ATTEMPTS", "5"))
PMC_FULLTEXT_RETRY_BACKOFF_BASE: float = float(os.getenv("PMC_FULLTEXT_RETRY_BACKOFF_BASE", "2.0"))
PMC_FULLTEXT_RETRY_BACKOFF_MAX: float = float(os.getenv("PMC_FULLTEXT_RETRY_BACKOFF_MAX", "10.0"))

# Embedding
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
EMBEDDING_DIM = 1024

# ChromaDB
CHROMA_PERSIST_PATH: str = os.getenv("CHROMA_PERSIST_PATH", "/chroma-data")
CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION_NAME", "paper_chunks")

# 청킹
CHUNK_MIN_TOKENS: int = int(os.getenv("CHUNK_MIN_TOKENS", "300"))
CHUNK_MAX_TOKENS: int = int(os.getenv("CHUNK_MAX_TOKENS", "512"))
CHUNK_OVERLAP_TOKENS: int = int(os.getenv("CHUNK_OVERLAP_TOKENS", "50"))

# 파이프라인
# NOTE: 카테고리당 후보 풀 cap은 OPENALEX_MAX_PER_CATEGORY / PUBMED_MAX_PER_CATEGORY로
# 소스별 분리되어 있다. legacy 단일 변수(MAX_PAPERS_PER_CATEGORY)는 crawl_papers가
# 참조하지 않아 dead였기 때문에 제거. CLI는 `--max-per-category`로 양쪽을 동시 override.
MAX_PAPERS_PER_RUN: int = int(os.getenv("MAX_PAPERS_PER_RUN", "300"))

# API 연동 (GitHub Actions → 서버 ChromaDB 적재)
API_BASE_URL: str = os.getenv("API_BASE_URL", "")
ADMIN_API_TOKEN: str = os.getenv("ADMIN_API_TOKEN", "")

# 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"

# OpenAlex
OPENALEX_BASE_URL: str = os.getenv("OPENALEX_BASE_URL", "https://api.openalex.org")
OPENALEX_MAILTO: str = os.getenv("OPENALEX_MAILTO", "")
OPENALEX_MAX_PER_CATEGORY: int = int(os.getenv("OPENALEX_MAX_PER_CATEGORY", "500"))
# 429 빈번 → 0.5s 간격 + 3회 재시도 + circuit breaker(3연속 실패 시 trip).
OPENALEX_RATE_LIMIT: float = float(os.getenv("OPENALEX_RATE_LIMIT", "0.5"))
OPENALEX_MAX_RETRIES: int = int(os.getenv("OPENALEX_MAX_RETRIES", "3"))
OPENALEX_CIRCUIT_BREAKER_THRESHOLD: int = int(os.getenv("OPENALEX_CIRCUIT_BREAKER_THRESHOLD", "3"))
PUBMED_MAX_PER_CATEGORY: int = int(os.getenv("PUBMED_MAX_PER_CATEGORY", "50"))

# Europe PMC
EUROPEPMC_BASE_URL: str = os.getenv("EUROPEPMC_BASE_URL", "https://www.ebi.ac.uk/europepmc/webservices/rest")
EUROPEPMC_RATE_LIMIT: float = float(os.getenv("EUROPEPMC_RATE_LIMIT", "1.0"))

# Publication-type 필터 토글
STRICT_PUBLICATION_FILTER: bool = _env_bool("STRICT_PUBLICATION_FILTER")
