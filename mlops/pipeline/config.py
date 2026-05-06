import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# PubMed
NCBI_API_KEY: str = os.getenv("NCBI_API_KEY", "")
NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_RATE_LIMIT: float = 0.34 if NCBI_API_KEY else 1.0  # 초 단위 대기

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
MAX_PAPERS_PER_RUN: int = int(os.getenv("MAX_PAPERS_PER_RUN", "100"))

# API 연동 (GitHub Actions → 서버 ChromaDB 적재)
API_BASE_URL: str = os.getenv("API_BASE_URL", "")
ADMIN_API_TOKEN: str = os.getenv("ADMIN_API_TOKEN", "")

# 경로
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
