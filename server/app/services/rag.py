"""RAG 파이프라인 서비스.

두 가지 기능:
1. chat_rag()    — 챗봇: 질문 → 논문 검색 → LLM 답변 + 논문 출처 카드
2. routine_rag() — 루틴 생성: 사용자 프로필 → 논문 검색 → LLM day별 JSON

로컬 테스트 (scifit-sync/ 루트에서 실행):
    python server/app/services/rag.py search          # ChromaDB 검색만 (LLM 불필요)
    python server/app/services/rag.py chat             # 챗봇 RAG (LLM 필요)
    python server/app/services/rag.py routine          # 루틴 생성 RAG (LLM 필요)
"""

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

# ── 프로젝트 루트 및 환경변수 로드 ────────────────────────────
# server/app/services/rag.py → parents[3] = scifit-sync/
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_env() -> None:
    """로컬 개발 시 mlops/.env에서 환경변수를 로드한다."""
    try:
        from dotenv import load_dotenv
        env_path = _PROJECT_ROOT / "mlops" / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass


_load_env()

# llm.py (같은 디렉토리) import
_SERVICES_DIR = Path(__file__).resolve().parent
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))
from llm import generate as llm_generate  # noqa: E402

# ── 설정 ──────────────────────────────────────────────────────
def _resolve_chroma_path() -> str:
    """상대 경로를 프로젝트 루트 기준 절대 경로로 변환한다."""
    raw = os.getenv("CHROMA_PERSIST_PATH", "./chroma-data")
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str(_PROJECT_ROOT / raw.lstrip("./").lstrip("\\"))


CHROMA_PERSIST_PATH = _resolve_chroma_path()
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "paper_chunks")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
BGE_INSTRUCTION = "Represent this document for retrieval: "
TOP_K = 10
SIMILARITY_THRESHOLD = 0.70

# ── 싱글턴 (lazy load) ────────────────────────────────────────
_chroma_collection = None
_embed_model = None


def _get_collection():
    """ChromaDB collection을 싱글턴으로 반환한다."""
    global _chroma_collection
    if _chroma_collection is None:
        import chromadb
        logger.info("ChromaDB 연결: %s", CHROMA_PERSIST_PATH)
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
        _chroma_collection = client.get_collection(CHROMA_COLLECTION_NAME)
        logger.info("ChromaDB 준비 완료 (문서 수: %d)", _chroma_collection.count())
    return _chroma_collection


def _get_embed_model():
    """BGE 임베딩 모델을 싱글턴으로 반환한다."""
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("임베딩 모델 로딩: %s", EMBEDDING_MODEL)
        _embed_model = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("임베딩 모델 로딩 완료")
    return _embed_model


# ── 핵심 함수 ─────────────────────────────────────────────────

def search_chunks(query: str, top_k: int = TOP_K) -> list[dict]:
    """쿼리를 임베딩하여 ChromaDB에서 유사 청크를 검색한다.

    Args:
        query: 검색 쿼리 (영어 권장)
        top_k: 최대 반환 수

    Returns:
        [{"content": str, "pmid": str, "title": str, "section": str, "score": float}]
    """
    model = _get_embed_model()
    collection = _get_collection()

    query_vec = model.encode(BGE_INSTRUCTION + query).tolist()
    results = collection.query(
        query_embeddings=[query_vec],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        # ChromaDB cosine distance → similarity (1 - distance)
        score = 1 - dist
        if score >= SIMILARITY_THRESHOLD:
            chunks.append({
                "content": doc,
                "pmid": meta.get("paper_pmid", ""),
                "title": meta.get("paper_title", ""),
                "section": meta.get("section_name", ""),
                "score": round(score, 4),
            })

    logger.info("검색 결과: %d개 (threshold=%.2f 이상)", len(chunks), SIMILARITY_THRESHOLD)
    return chunks


def translate_to_english(text: str) -> str:
    """한국어 텍스트를 영어로 번역한다. 실패 시 원문을 반환한다."""
    korean_chars = sum(1 for c in text if "가" <= c <= "힣")
    if korean_chars < 3:
        return text  # 영어면 번역 불필요

    try:
        translated = llm_generate(
            "Translate the following Korean fitness/exercise query to English. "
            "Return only the translation, no explanation.\n\n"
            f"{text}"
        )
        logger.info("번역: '%s' → '%s'", text[:30], translated[:50])
        return translated
    except Exception as e:
        logger.warning("번역 실패, 원문 사용: %s", e)
        return text


def chat_rag(question: str) -> dict:
    """챗봇 RAG: 질문 → 논문 검색 → LLM 답변 + 논문 출처 카드.

    Args:
        question: 사용자 질문 (한국어 가능)

    Returns:
        {
            "answer": str,
            "sources": [{"pmid": str, "title": str, "section": str}]
        }
    """
    # 1. 한→영 번역 (실패 시 원문 사용)
    query_en = translate_to_english(question)

    # 2. ChromaDB 검색
    chunks = search_chunks(query_en)
    if not chunks:
        # fallback: 원문으로 재검색
        logger.info("번역 검색 결과 없음, 원문으로 재검색")
        chunks = search_chunks(question)

    if not chunks:
        return {
            "answer": "관련 논문을 찾을 수 없습니다. 다른 방식으로 질문해 주세요.",
            "sources": [],
        }

    # 3. 프롬프트 구성 (상위 5개 청크 사용)
    context = ""
    for i, chunk in enumerate(chunks[:5], 1):
        context += (
            f"\n[논문 {i}] {chunk['title']} — {chunk['section']}\n"
            f"{chunk['content'][:400]}\n"
        )

    prompt = (
        "You are a sports science expert. Answer the question based ONLY on the provided research papers.\n"
        "Always cite which paper supports each claim.\n"
        "If the papers don't contain relevant information, say so clearly.\n\n"
        f"Research papers:\n{context}\n"
        f"<user_query>{question}</user_query>\n\n"
        "Answer in Korean. Be specific and cite paper titles."
    )

    # 4. LLM 답변 생성
    answer = llm_generate(prompt)

    # 5. 출처 카드 구성 (중복 제거)
    seen: set[str] = set()
    sources = []
    for chunk in chunks[:5]:
        if chunk["pmid"] not in seen:
            seen.add(chunk["pmid"])
            sources.append({
                "pmid": chunk["pmid"],
                "title": chunk["title"],
                "section": chunk["section"],
            })

    return {
        "answer": answer,
        "sources": sources,
    }


@dataclass
class UserProfile:
    """루틴 생성에 필요한 사용자 프로필."""
    goal: str                              # hypertrophy / strength / endurance / rehabilitation
    body_weight: float                     # kg
    fitness_career: str                    # beginner / intermediate / advanced
    days_per_week: int                     # 주당 운동 일수
    available_equipment: list[str] = field(default_factory=list)  # 사용 가능한 기구


def routine_rag(profile: UserProfile) -> Generator[dict, None, None]:
    """루틴 생성 RAG: 프로필 → 논문 검색 → LLM → day별 JSON 스트리밍.

    Args:
        profile: 사용자 프로필

    Yields:
        {"type": "day_complete", "day": int, "focus": str, "exercises": [...]}
        {"type": "done"}
        {"type": "error", "message": str}
    """
    # 1. 목표별 검색 쿼리
    goal_queries = {
        "hypertrophy": "muscle hypertrophy resistance training volume sets reps",
        "strength":    "strength training progressive overload 1RM powerlifting",
        "endurance":   "muscular endurance high repetition aerobic training",
        "rehabilitation": "rehabilitation exercise low intensity recovery injury",
    }
    query = goal_queries.get(profile.goal, profile.goal)

    # 2. ChromaDB 검색
    chunks = search_chunks(query)
    if not chunks:
        yield {"type": "error", "message": "관련 논문을 찾을 수 없습니다."}
        return

    # 3. 컨텍스트 구성
    context = ""
    for i, chunk in enumerate(chunks[:5], 1):
        context += (
            f"\n[Paper {i}] {chunk['title']} — {chunk['section']}\n"
            f"{chunk['content'][:300]}\n"
        )

    equipment_str = (
        ", ".join(profile.available_equipment)
        if profile.available_equipment
        else "barbell, dumbbell, bodyweight"
    )

    # 4. 루틴 생성 프롬프트
    prompt = (
        f"You are a sports science expert. Create a {profile.days_per_week}-day workout routine "
        f"based on the research papers below.\n\n"
        f"User Profile:\n"
        f"- Goal: {profile.goal}\n"
        f"- Body weight: {profile.body_weight}kg\n"
        f"- Fitness level: {profile.fitness_career}\n"
        f"- Available equipment: {equipment_str}\n\n"
        f"Research papers:\n{context}\n\n"
        f"Output a JSON array of exactly {profile.days_per_week} day objects.\n"
        f"Each object format:\n"
        f'{{"day": <number>, "focus": "<muscle group>", "exercises": ['
        f'{{"name": "<exercise>", "sets": <number>, "reps": "<e.g. 8-12>", '
        f'"rest_seconds": <number>, "notes": "<paper-based rationale>"}}]}}\n\n'
        f"Output ONLY valid JSON array. No markdown, no explanation."
    )

    raw = llm_generate(prompt)

    # 5. JSON 파싱 및 day별 yield
    try:
        # 마크다운 코드블록 제거
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
            raw = raw.rsplit("```", 1)[0].strip()

        days = json.loads(raw)
        for day_data in days:
            yield {"type": "day_complete", **day_data}
        yield {"type": "done"}

    except json.JSONDecodeError as e:
        logger.error("루틴 JSON 파싱 실패: %s\n원문: %.200s", e, raw)
        yield {"type": "error", "message": "루틴 생성 중 오류가 발생했습니다."}


# ── 로컬 테스트 ───────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
    )

    mode = sys.argv[1] if len(sys.argv) > 1 else "search"

    if mode == "search":
        # ── ChromaDB 검색 테스트 (LLM 불필요) ──────────────
        print("\n=== ChromaDB 검색 테스트 ===")
        query = "resistance training muscle hypertrophy"
        results = search_chunks(query)
        print(f"\n쿼리: '{query}'")
        print(f"결과: {len(results)}개 (threshold={SIMILARITY_THRESHOLD} 이상)\n")
        for i, r in enumerate(results[:3], 1):
            print(f"[{i}] score={r['score']} | {r['title']}")
            print(f"     섹션: {r['section']}")
            print(f"     내용: {r['content'][:150]}...")
            print()

    elif mode == "chat":
        # ── 챗봇 RAG 테스트 (LLM 필요) ────────────────────
        print("\n=== 챗봇 RAG 테스트 (종료: quit) ===\n")
        while True:
            question = input("질문: ").strip()
            if question.lower() in ("quit", "exit", "종료"):
                break
            if not question:
                continue
            result = chat_rag(question)
            print(f"\n[답변]\n{result['answer']}\n")
            print("[출처 논문]")
            for s in result["sources"]:
                print(f"  - {s['title']} / {s['section']} (PMID: {s['pmid']})")
            print()

    elif mode == "routine":
        # ── 루틴 생성 테스트 (LLM 필요) ───────────────────
        print("\n=== 루틴 생성 RAG 테스트 ===\n")
        profile = UserProfile(
            goal="hypertrophy",
            body_weight=75.0,
            fitness_career="intermediate",
            days_per_week=3,
            available_equipment=["barbell", "dumbbell", "cable"],
        )
        print(f"프로필: 목표={profile.goal}, 체중={profile.body_weight}kg, "
              f"레벨={profile.fitness_career}, 주{profile.days_per_week}일\n")

        for event in routine_rag(profile):
            if event["type"] == "day_complete":
                print(f"[Day {event['day']}] {event.get('focus', '')}")
                for ex in event.get("exercises", []):
                    print(f"  - {ex['name']}: {ex['sets']}세트 × {ex['reps']}회  "
                          f"(휴식 {ex.get('rest_seconds', '?')}초)")
                    if ex.get("notes"):
                        print(f"    근거: {ex['notes'][:80]}")
                print()
            elif event["type"] == "done":
                print("루틴 생성 완료")
            elif event["type"] == "error":
                print(f"오류: {event['message']}")

    else:
        print("사용법: python server/app/services/rag.py [search|chat|routine]")
