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
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path

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
from llm import generate as llm_generate  # noqa: E402, I001
from llm import generate_stream as llm_generate_stream  # noqa: E402, I001


# ── 설정 ──────────────────────────────────────────────────────
def _resolve_chroma_path() -> str:
    """ChromaDB 데이터 경로를 결정한다.

    컨테이너 환경(/chroma-data 마운트)과 로컬 개발 환경(WSL/macOS)을 자동 분기한다:
    - 절대 경로: 쓰기 가능하면 그대로 사용, 권한 없으면 프로젝트 루트의 chroma-data로 fallback
    - 상대 경로: 프로젝트 루트 기준으로 변환
    """
    raw = os.getenv("CHROMA_PERSIST_PATH", "./chroma-data")
    p = Path(raw)
    if p.is_absolute():
        if p.exists() and os.access(p, os.W_OK):
            return str(p)
        fallback = _PROJECT_ROOT / "chroma-data"
        logger.warning("CHROMA_PERSIST_PATH=%s 접근 불가, 로컬 경로 %s로 fallback", raw, fallback)
        return str(fallback)
    return str(_PROJECT_ROOT / raw.lstrip("./").lstrip("\\"))


CHROMA_PERSIST_PATH = _resolve_chroma_path()
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "paper_chunks")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
TOP_K = 10
SIMILARITY_THRESHOLD = 0.70
# Task 13: evidence_weight 가중치 정렬
OVER_FETCH_MULTIPLIER = 3
DEFAULT_EVIDENCE_WEIGHT = 0.50

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


def _sanitize_query(text: str) -> str:
    """UTF-8로 인코딩 불가한 surrogate 문자(U+D800–U+DFFF)를 제거한다.

    WSL/Windows 콘솔의 input()이 일부 한글을 lone surrogate로 반환하는 경우
    sentence-transformers tokenizer가 TypeError("TextEncodeInput must be ...")를 던진다.
    Gemini API도 surrogate 포함 문자열을 거부하므로 임베딩·번역 진입 전 일괄 정화한다.
    """
    return text.encode("utf-8", errors="ignore").decode("utf-8").strip()


def _rank_by_evidence_weight(
    raw_results: list[dict],
    *,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> list[dict]:
    """raw_results를 evidence_weight 가중 점수로 정렬한다 (Task 13).

    Args:
        raw_results: 각 항목은 ``{"distance": float, "metadata": dict, "document": str}``
        similarity_threshold: raw similarity 컷오프 (가중 점수가 아닌 원본 유사도 기준).
            약한 evidence_weight 청크라도 유사도가 충분히 높으면 통과시키기 위함.

    Returns:
        [{
            "score": similarity × evidence_weight,
            "similarity": float,
            "weight": float,
            "metadata": dict,
            "document": str,
        }] — score 내림차순.
    """
    ranked: list[dict] = []
    for r in raw_results:
        similarity = 1.0 - float(r["distance"])
        meta = r.get("metadata") or {}
        raw_weight = meta.get("evidence_weight", DEFAULT_EVIDENCE_WEIGHT)
        try:
            weight = float(raw_weight) if raw_weight is not None else DEFAULT_EVIDENCE_WEIGHT
        except (TypeError, ValueError):
            weight = DEFAULT_EVIDENCE_WEIGHT
        ranked.append(
            {
                "score": similarity * weight,
                "similarity": similarity,
                "weight": weight,
                "metadata": meta,
                "document": r.get("document", ""),
            }
        )
    ranked = [r for r in ranked if r["similarity"] >= similarity_threshold]
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def search_chunks(query: str, top_k: int = TOP_K) -> list[dict]:
    """쿼리를 임베딩하여 ChromaDB에서 유사 청크를 검색한다.

    Task 13: ``top_k × OVER_FETCH_MULTIPLIER`` 만큼 over-fetch 한 뒤
    ``similarity × evidence_weight`` 가중 점수로 재정렬하고 상위 ``top_k`` 만 반환한다.
    threshold 필터는 raw similarity 기준으로 유지.

    Args:
        query: 검색 쿼리 (영어 권장)
        top_k: 최대 반환 수

    Returns:
        [{"content": str, "pmid": str, "title": str, "section": str, "score": float}]
    """
    query = _sanitize_query(query)
    if not query:
        return []

    model = _get_embed_model()
    collection = _get_collection()

    query_vec = model.encode(BGE_QUERY_INSTRUCTION + query).tolist()
    fetch_n = top_k * OVER_FETCH_MULTIPLIER
    results = collection.query(
        query_embeddings=[query_vec],
        n_results=fetch_n,
        include=["documents", "metadatas", "distances"],
    )

    raw_items: list[dict] = [
        {"distance": dist, "metadata": meta, "document": doc}
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
            strict=False,
        )
    ]
    ranked = _rank_by_evidence_weight(raw_items, similarity_threshold=SIMILARITY_THRESHOLD)

    chunks = [
        {
            "content": r["document"],
            "pmid": (r["metadata"] or {}).get("paper_pmid", ""),
            "title": (r["metadata"] or {}).get("paper_title", ""),
            "section": (r["metadata"] or {}).get("section_name", ""),
            "score": round(r["score"], 4),
        }
        for r in ranked[:top_k]
    ]

    logger.info(
        "검색 결과: %d개 (fetched=%d, threshold=%.2f, weighted)",
        len(chunks),
        len(raw_items),
        SIMILARITY_THRESHOLD,
    )
    return chunks


def translate_to_english(text: str) -> str:
    """한국어 텍스트를 영어로 번역한다. 실패 시 원문을 반환한다."""
    text = _sanitize_query(text)
    korean_chars = sum(1 for c in text if "가" <= c <= "힣")
    if korean_chars < 3:
        return text  # 영어면 번역 불필요

    try:
        translated = llm_generate(
            "Translate the following Korean fitness/exercise query to English. "
            "Return only the translation, no explanation.\n\n"
            f"<user_query>{text}</user_query>"
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
    question = _sanitize_query(question)
    if not question:
        return {"answer": "질문을 인식할 수 없습니다. 다시 입력해 주세요.", "sources": []}

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
        context += f"\n[논문 {i}] {chunk['title']} — {chunk['section']}\n{chunk['content'][:400]}\n"

    safe_question = question.replace("</user_query>", "</ user_query>")
    prompt = (
        "You are a sports science expert. Answer the question based ONLY on the provided research papers.\n"
        "Always cite which paper supports each claim.\n"
        "If the papers don't contain relevant information, say so clearly.\n\n"
        f"Research papers:\n{context}\n"
        f"<user_query>{safe_question}</user_query>\n\n"
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
            sources.append(
                {
                    "pmid": chunk["pmid"],
                    "title": chunk["title"],
                    "section": chunk["section"],
                }
            )

    return {
        "answer": answer,
        "sources": sources,
    }


@dataclass
class UserProfile:
    """루틴 생성에 필요한 사용자 프로필.

    `goals`는 복수 선택 (D-M6, CLAUDE.md §6). 첫 번째 목표가 검색 쿼리의 기준이 되고
    나머지는 LLM 프롬프트에 함께 전달된다.
    """

    goals: list[str]  # hypertrophy | strength | endurance | rehabilitation | weight_loss
    body_weight: float  # kg
    fitness_career: str  # beginner / novice / intermediate / advanced
    days_per_week: int  # 주당 운동 일수 (split_type에서 derive)
    available_equipment: list[str] = field(default_factory=list)  # 사용 가능한 기구명
    target_muscles: list[str] = field(default_factory=list)  # 집중하고 싶은 근육 부위
    session_minutes: int | None = None  # 1회 세션 목표 시간
    injury: str | None = None  # 부상/제외 부위 (자유 텍스트)
    feedback: str | None = None  # 재생성 시 이전 루틴 대비 변경 요청

    @property
    def primary_goal(self) -> str:
        """검색 쿼리·중량 계산용 대표 목표 (목록 첫 번째, 소문자)."""
        if not self.goals:
            return "hypertrophy"
        return self.goals[0].lower()


_GOAL_QUERIES = {
    "hypertrophy": "muscle hypertrophy resistance training volume sets reps",
    "strength": "strength training progressive overload 1RM powerlifting",
    "endurance": "muscular endurance high repetition aerobic training",
    "rehabilitation": "rehabilitation exercise low intensity recovery injury",
    "weight_loss": "fat loss body composition energy expenditure resistance training",
}


def _build_routine_prompt(profile: UserProfile, chunks: list[dict]) -> str:
    """루틴 생성 프롬프트를 조합한다. 외부 청크는 별도 섹션으로 분리한다."""
    context = ""
    for i, chunk in enumerate(chunks[:5], 1):
        context += f"\n[Paper {i}] {chunk['title']} — {chunk['section']}\n{chunk['content'][:300]}\n"

    equipment_str = (
        ", ".join(profile.available_equipment) if profile.available_equipment else "barbell, dumbbell, bodyweight"
    )
    goals_str = ", ".join(g.lower() for g in profile.goals) if profile.goals else "hypertrophy"
    muscles_str = ", ".join(profile.target_muscles) if profile.target_muscles else "balanced full-body"

    extras = []
    if profile.session_minutes:
        extras.append(f"- Target session duration: ~{profile.session_minutes} minutes")
    if profile.injury:
        # 사용자 입력은 <user_query> 태그로 격리 (CLAUDE.md §12 프롬프트 인젝션 방어)
        safe = profile.injury.replace("</user_query>", "</ user_query>")
        extras.append(f"- Injury/exclusion constraints (from user): <user_query>{safe}</user_query>")
    if profile.feedback:
        safe = profile.feedback.replace("</user_query>", "</ user_query>")
        extras.append(f"- Regenerate feedback (from user): <user_query>{safe}</user_query>")
    extras_str = ("\n" + "\n".join(extras)) if extras else ""

    return (
        f"You are a sports science expert. Create a {profile.days_per_week}-day workout routine "
        f"based ONLY on the research papers below.\n\n"
        f"User Profile:\n"
        f"- Goals (primary first): {goals_str}\n"
        f"- Target muscles to emphasize: {muscles_str}\n"
        f"- Body weight: {profile.body_weight}kg\n"
        f"- Fitness level: {profile.fitness_career}\n"
        f"- Available equipment: {equipment_str}"
        f"{extras_str}\n\n"
        f"Research papers:\n{context}\n\n"
        f"Output a JSON array of exactly {profile.days_per_week} day objects.\n"
        f"Each object format:\n"
        f'{{"day": <number>, "focus": "<muscle group>", "exercises": ['
        f'{{"name": "<English exercise name>", "sets": <number>, '
        f'"reps_min": <number>, "reps_max": <number>, '
        f'"rest_seconds": <number>, "equipment_type": "<cable|machine|barbell|dumbbell|bodyweight>", '
        f'"notes": "<paper-based rationale, mention paper number>"}}]}}\n\n'
        f"Use rep ranges that match the primary goal (hypertrophy 8-12, strength 1-5, "
        f"endurance 15-20, rehabilitation 20-30).\n"
        f"Output ONLY valid JSON array. No markdown, no explanation, no surrounding text."
    )


def _strip_markdown_fence(raw: str) -> str:
    """LLM이 ```json ... ``` 코드블록을 감싸서 보내는 경우 제거."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        # 첫 줄(```json) 제거
        lines = lines[1:]
        # 마지막 ``` 제거
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def routine_rag_stream(profile: UserProfile) -> Generator[dict, None, None]:
    """루틴 생성 RAG (스트리밍): 프로필 → 논문 검색 → LLM 토큰 스트림 → day별 JSON.

    CLAUDE.md §11 RAG 파이프라인 6단계 + §7 SSE 포맷 (chunk/day_complete/done)을 따른다.

    Yields:
        {"type": "chunk", "content": str}              # LLM delta 토큰 (실시간)
        {"type": "day_complete", "day": int, "focus": str, "exercises": [...]}
        {"type": "papers", "sources": [{"pmid", "title", "section", "score"}]}
        {"type": "done"}
        {"type": "error", "message": str}
    """
    # 1. 목표별 검색 쿼리 (1차 목표 기준)
    primary = profile.primary_goal
    query = _GOAL_QUERIES.get(primary, primary)
    # 보조 목표 + 타겟 근육이 있으면 쿼리에 추가
    extras = [g.lower() for g in profile.goals[1:]] + profile.target_muscles
    if extras:
        query = f"{query} {' '.join(extras)}"

    # 2. ChromaDB 검색
    chunks = search_chunks(query)
    if not chunks:
        yield {"type": "error", "message": "관련 논문을 찾을 수 없습니다."}
        return

    # 3. 프롬프트 조합
    prompt = _build_routine_prompt(profile, chunks)

    # 4. LLM 토큰 스트리밍
    raw_parts: list[str] = []
    try:
        for token in llm_generate_stream(prompt):
            raw_parts.append(token)
            yield {"type": "chunk", "content": token}
    except Exception as e:
        logger.error("LLM 스트리밍 실패: %s", e)
        yield {"type": "error", "message": "AI 응답 생성 중 오류가 발생했습니다."}
        return

    raw = "".join(raw_parts)

    # 5. JSON 파싱 및 day별 yield
    try:
        days = json.loads(_strip_markdown_fence(raw))
    except json.JSONDecodeError as e:
        logger.error("루틴 JSON 파싱 실패: %s\n원문: %.200s", e, raw)
        yield {"type": "error", "message": "루틴 생성 결과를 해석할 수 없습니다."}
        return

    if not isinstance(days, list):
        logger.error("루틴 JSON이 배열이 아님: %r", days)
        yield {"type": "error", "message": "루틴 생성 결과 형식이 올바르지 않습니다."}
        return

    for day_data in days:
        if isinstance(day_data, dict):
            yield {"type": "day_complete", **day_data}

    # 6. 사용된 논문 출처 (중복 pmid 제거)
    seen: set[str] = set()
    sources: list[dict] = []
    for chunk in chunks[:5]:
        pmid = chunk.get("pmid") or ""
        if pmid and pmid not in seen:
            seen.add(pmid)
            sources.append(
                {
                    "pmid": pmid,
                    "title": chunk.get("title", ""),
                    "section": chunk.get("section", ""),
                    "score": chunk.get("score"),
                }
            )
    if sources:
        yield {"type": "papers", "sources": sources}

    yield {"type": "done"}


def routine_rag(profile: UserProfile) -> Generator[dict, None, None]:
    """루틴 생성 RAG (비스트리밍 호환): routine_rag_stream에서 chunk 이벤트만 제외.

    기존 CLI 테스트 (`python rag.py routine`)와 하위 호환을 위해 유지한다.
    """
    for event in routine_rag_stream(profile):
        if event.get("type") != "chunk":
            yield event


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
            goals=["hypertrophy", "strength"],
            body_weight=75.0,
            fitness_career="intermediate",
            days_per_week=3,
            available_equipment=["barbell", "dumbbell", "cable"],
            target_muscles=["chest", "triceps"],
            session_minutes=75,
        )
        print(
            f"프로필: 목표={profile.goals}, 체중={profile.body_weight}kg, "
            f"레벨={profile.fitness_career}, 주{profile.days_per_week}일\n"
        )

        for event in routine_rag(profile):
            etype = event["type"]
            if etype == "day_complete":
                print(f"[Day {event['day']}] {event.get('focus', '')}")
                for ex in event.get("exercises", []):
                    reps = f"{ex.get('reps_min', '?')}-{ex.get('reps_max', '?')}"
                    print(
                        f"  - {ex['name']}: {ex['sets']}세트 × {reps}회  "
                        f"(휴식 {ex.get('rest_seconds', '?')}초)"
                    )
                    if ex.get("notes"):
                        print(f"    근거: {ex['notes'][:80]}")
                print()
            elif etype == "papers":
                print("[근거 논문]")
                for s in event["sources"]:
                    print(f"  - {s['title']} / {s['section']} (PMID: {s['pmid']})")
                print()
            elif etype == "done":
                print("루틴 생성 완료")
            elif etype == "error":
                print(f"오류: {event['message']}")

    else:
        print("사용법: python server/app/services/rag.py [search|chat|routine]")
