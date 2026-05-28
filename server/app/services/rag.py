"""RAG 파이프라인 서비스 — chat_rag_stream (챗봇) 및 routine_rag_stream (루틴 생성)."""

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
    """ChromaDB 데이터 경로 결정 (컨테이너 /chroma-data 마운트 vs 로컬 fallback)."""
    # 기본값은 서버 config.py / mlops config와 동일한 절대경로(EFS 마운트)로 통일.
    # ECS 태스크에 env가 명시되지 않아도 admin(쓰기)과 동일한 /chroma-data를 읽도록 한다.
    raw = os.getenv("CHROMA_PERSIST_PATH", "/chroma-data")
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

# ── Alias-swap (PR-δ §2.3) ────────────────────────────────────
# EFS /chroma-data/current_alias.json을 SOT로 사용해 모든 ECS 태스크가 같은 alias를 본다.
# admin endpoint(POST /admin/rag/collection-swap)가 atomic write 하고 cache를 clear하면,
# 다음 _get_collection 호출부터 새 alias가 반영된다.
ALIAS_FILE = Path(CHROMA_PERSIST_PATH) / "current_alias.json"
# alias 미설정/손상 시 fallback. PR-δ §2.3은 정규화 후 'papers'를 default로 명시.
# 현재 운영 collection명(CHROMA_COLLECTION_NAME=paper_chunks)과 다르므로 마이그레이션 시점에
# admin endpoint로 alias를 명시적으로 'paper_chunks' 등 운영명으로 swap해두는 것이 안전하다.
DEFAULT_COLLECTION = "papers"

# ── 싱글턴 (lazy load) ────────────────────────────────────────
_client = None
_collection_cache: dict[str, object] = {}
_embed_model = None


def _current_collection_name() -> str:
    """alias 파일을 읽어 현재 collection 이름을 반환. missing/corrupt는 기본값 fallback."""
    try:
        if ALIAS_FILE.exists():
            data = json.loads(ALIAS_FILE.read_text(encoding="utf-8"))
            name = data.get("current", DEFAULT_COLLECTION)
            if isinstance(name, str) and name.strip():
                return name
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("alias 파일 읽기 실패: %s, 기본 collection 사용", e)
    return DEFAULT_COLLECTION


def _get_collection():
    """현재 alias가 가리키는 ChromaDB collection을 반환.

    매 호출마다 alias 파일(`ALIAS_FILE`)을 확인해 swap을 즉시 반영한다.
    collection 핸들은 이름별로 캐시되므로 reload 비용은 alias 변경 시점에만 발생한다.
    """
    global _client
    name = _current_collection_name()
    if name not in _collection_cache:
        if _client is None:
            import chromadb

            logger.info("ChromaDB 연결: %s", CHROMA_PERSIST_PATH)
            _client = chromadb.PersistentClient(path=CHROMA_PERSIST_PATH)
        collection = _client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        count = collection.count()
        if count == 0:
            logger.warning(
                "ChromaDB 컬렉션 '%s'이 비어 있습니다 (문서 0개). 파이프라인을 재실행하세요.",
                name,
            )
        else:
            logger.info("ChromaDB 준비 완료 (collection=%s, 문서 수: %d)", name, count)
        _collection_cache[name] = collection
    return _collection_cache[name]


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
    """WSL/Gemini API에서 문제를 일으키는 lone surrogate(U+D800–U+DFFF)를 제거."""
    return text.encode("utf-8", errors="ignore").decode("utf-8").strip()


def _rank_by_evidence_weight(
    raw_results: list[dict],
    *,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> list[dict]:
    """similarity × evidence_weight 가중 점수로 재정렬 후 threshold 미만 제거."""
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
    """쿼리 임베딩 → ChromaDB over-fetch → evidence_weight 가중 재정렬 → 상위 top_k 반환."""
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
            "doi": (r["metadata"] or {}).get("paper_doi", ""),
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

    # 사용자 입력은 <user_query> 태그로 격리 (CLAUDE.md §12 프롬프트 인젝션 방어)
    safe_text = text.replace("</user_query>", "</ user_query>")
    try:
        translated = llm_generate(
            "Translate the following Korean fitness/exercise query to English. "
            "Return only the translation, no explanation.\n\n"
            f"<user_query>{safe_text}</user_query>"
        )
        logger.info("번역: '%s' → '%s'", text[:30], translated[:50])
        return translated
    except Exception as e:
        logger.warning("번역 실패, 원문 사용: %s", e)
        return text


def chat_rag(question: str) -> dict:
    """챗봇 RAG (비스트리밍): 질문 → ChromaDB 검색 → LLM 답변 + 논문 출처 카드 반환."""
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

    # 5. 출처 카드 구성 (DOI 우선 dedup — DOI가 primary identifier, D-M11)
    seen: set[str] = set()
    sources = []
    for chunk in chunks[:5]:
        doi = chunk.get("doi") or ""
        pmid = chunk.get("pmid") or ""
        dedup_key = doi or pmid
        if not dedup_key or dedup_key in seen:
            continue
        seen.add(dedup_key)
        sources.append(
            {
                "doi": doi,
                "pmid": pmid,
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
    """루틴 생성용 사용자 프로필 (goals 첫 번째가 검색 기준, 나머지는 프롬프트 보조)."""

    goals: list[str]  # hypertrophy | strength | endurance | rehabilitation | weight_loss
    body_weight: float  # kg
    fitness_career: str  # beginner / novice / intermediate / advanced
    available_exercises: list[str] = field(default_factory=list)  # gym 기구로 할 수 있는 운동 name_en 목록
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

    goals_str = ", ".join(g.lower() for g in profile.goals) if profile.goals else "hypertrophy"
    muscles_str = ", ".join(profile.target_muscles) if profile.target_muscles else "balanced full-body"

    if profile.available_exercises:
        exercise_list_str = "\n".join(f"- {name}" for name in profile.available_exercises)
        exercises_section = (
            f"\nAvailable exercises at this gym (use ONLY these exact names — do not invent other names):\n"
            f"{exercise_list_str}\n"
        )
    else:
        exercises_section = "\nAvailable equipment: barbell, dumbbell, bodyweight (standard exercises allowed)\n"

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

    name_rule = (
        '- "name" must be chosen EXACTLY from the Available exercises list above. Do not invent or paraphrase names.\n'
        if profile.available_exercises
        else ""
    )

    return (
        f"You are a sports science expert. Create a 1-day workout routine "
        f"based ONLY on the research papers below.\n\n"
        f"User Profile:\n"
        f"- Goals (primary first): {goals_str}\n"
        f"- Target muscles to emphasize: {muscles_str}\n"
        f"- Body weight: {profile.body_weight}kg\n"
        f"- Fitness level: {profile.fitness_career}"
        f"{exercises_section}"
        f"{extras_str}\n\n"
        f"Research papers:\n{context}\n\n"
        f"Output a JSON array of exactly 1 day object.\n"
        f"Each object format:\n"
        f'{{"day": <number>, "focus": "<muscle group>", "exercises": ['
        f'{{"name": "<exercise name>", "sets": <number>, '
        f'"reps_min": <number>, "reps_max": <number>, '
        f'"rest_seconds": <number>, "equipment_type": "<cable|machine|barbell|dumbbell|bodyweight>", '
        f'"notes": "<Korean sentence explaining WHY this exercise was chosen based on the paper evidence. '
        f'Example: 30도 인클라인이 대흉근 상부 활성도를 15도보다 높게 활성화한다는 연구 결과를 근거로 선택하였습니다.", '
        f'"paper_index": <integer 1-5, the Paper number that most directly supports this exercise choice>}}]}}\n\n'
        f"Rules:\n"
        f"{name_rule}"
        f"- notes must be written in Korean and explain the specific finding from the paper.\n"
        f"- paper_index must be an integer (1 to {min(5, len(chunks))}), referring to the [Paper N] above.\n"
        f"- Use rep ranges that match the primary goal (hypertrophy 8-12, strength 1-5, "
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


def chat_rag_stream(
    question: str,
    history: list[dict] | None = None,
) -> Generator[dict, None, None]:
    """챗봇 RAG (스트리밍): 질문 + 대화 히스토리 → 논문 검색 → LLM 토큰 스트림 + 출처 카드."""
    question = _sanitize_query(question)
    if not question:
        yield {"type": "error", "message": "질문을 인식할 수 없습니다. 다시 입력해 주세요."}
        return

    # 1. 한→영 번역 (실패 시 원문 사용)
    query_en = translate_to_english(question)

    # 2. ChromaDB 검색
    chunks = search_chunks(query_en)
    if not chunks:
        logger.info("번역 검색 결과 없음, 원문으로 재검색")
        chunks = search_chunks(question)

    if not chunks:
        yield {"type": "error", "message": "관련 논문을 찾을 수 없습니다. 다른 방식으로 질문해 주세요."}
        return

    # 3. 프롬프트 구성 (상위 5개 청크 + 대화 히스토리)
    context = ""
    for i, chunk in enumerate(chunks[:5], 1):
        context += f"\n[논문 {i}] {chunk['title']} — {chunk['section']}\n{chunk['content'][:400]}\n"

    history_text = ""
    if history:
        for msg in history[-10:]:  # 최근 5턴(10메시지)
            role_label = "User" if msg["role"] == "user" else "Assistant"
            content = msg["content"][:300].replace("</user_query>", "</ user_query>")
            if msg["role"] == "user":
                history_text += f"{role_label}: <user_query>{content}</user_query>\n"
            else:
                history_text += f"{role_label}: {content}\n"

    safe_question = question.replace("</user_query>", "</ user_query>")
    prompt = (
        "You are a sports science expert. Answer the question based ONLY on the provided research papers.\n"
        "Always cite which paper supports each claim.\n"
        "If the papers don't contain relevant information, say so clearly.\n\n"
        f"Research papers:\n{context}\n"
    )
    if history_text:
        prompt += f"\nPrevious conversation:\n{history_text}\n"
    prompt += f"<user_query>{safe_question}</user_query>\n\nAnswer in Korean. Be specific and cite paper titles."

    # 4. LLM 토큰 스트리밍
    try:
        for token in llm_generate_stream(prompt):
            yield {"type": "chunk", "content": token}
    except Exception as e:
        logger.error("LLM 스트리밍 실패: %s", e)
        yield {"type": "error", "message": "AI 응답 생성 중 오류가 발생했습니다."}
        return

    # 5. 출처 카드 (DOI 우선 dedup — DOI가 primary identifier, D-M11)
    seen: set[str] = set()
    sources: list[dict] = []
    for chunk in chunks[:5]:
        doi = chunk.get("doi") or ""
        pmid = chunk.get("pmid") or ""
        dedup_key = doi or pmid
        if not dedup_key or dedup_key in seen:
            continue
        seen.add(dedup_key)
        sources.append({"doi": doi, "pmid": pmid, "title": chunk.get("title", ""), "section": chunk.get("section", "")})
    if sources:
        yield {"type": "sources", "sources": sources}

    yield {"type": "done"}


def routine_rag_stream(profile: UserProfile) -> Generator[dict, None, None]:
    """루틴 생성 RAG (스트리밍): chunk / day_complete / papers / done / error 이벤트를 yield."""
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

    # 6. 사용된 논문 출처 (DOI 기준 dedup — DOI가 primary identifier, D-M11)
    seen: set[str] = set()
    sources: list[dict] = []
    for chunk in chunks[:5]:
        doi = chunk.get("doi") or ""
        pmid = chunk.get("pmid") or ""
        dedup_key = doi or pmid  # DOI 우선, 없으면 PMID로 dedup
        if not dedup_key or dedup_key in seen:
            continue
        seen.add(dedup_key)
        sources.append(
            {
                "doi": doi,
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
    """routine_rag_stream의 chunk 이벤트를 제외한 비스트리밍 호환 래퍼."""
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
            available_exercises=["Bench Press", "Incline Bench Press", "Cable Fly", "Tricep Pushdown", "Dumbbell Fly"],
            target_muscles=["chest", "triceps"],
            session_minutes=75,
        )
        print(f"프로필: 목표={profile.goals}, 체중={profile.body_weight}kg, 레벨={profile.fitness_career}\n")

        for event in routine_rag(profile):
            etype = event["type"]
            if etype == "day_complete":
                print(f"[Day {event['day']}] {event.get('focus', '')}")
                for ex in event.get("exercises", []):
                    reps = f"{ex.get('reps_min', '?')}-{ex.get('reps_max', '?')}"
                    print(f"  - {ex['name']}: {ex['sets']}세트 × {reps}회  (휴식 {ex.get('rest_seconds', '?')}초)")
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
