"""RAG retrieval 자동 평가 스크립트.

골드셋(JSONL) → recall@5, recall@10, MRR 계산 → Markdown 리포트.

사용법:
    python -m mlops.eval.run_eval \
        --goldset mlops/eval/gold_set.jsonl \
        --output mlops/eval/reports/2026-05-19.md

테스트에서는 ``run_evaluation`` / ``main`` 에 mock retriever 콜러블을 주입한다.
"""

import argparse
import gzip
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_TOP_K_VALUES: tuple[int, ...] = (5, 10)
# chunk-level over-fetch 배율 — paper-level top_k 보장용 (server.search_chunks와 동일 컨셉).
DEFAULT_CHUNK_OVER_FETCH = 3

Retriever = Callable[[str, int], list[dict]]


@dataclass(frozen=True)
class GoldSetItem:
    """골드셋 한 줄 = 하나의 평가 질의."""

    id: str
    query: str
    category: str
    expected_pmids: tuple[str, ...]
    expected_dois: tuple[str, ...] = ()
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "GoldSetItem":
        return cls(
            id=str(raw["id"]),
            query=str(raw["query"]),
            category=str(raw["category"]),
            expected_pmids=tuple(str(p) for p in raw.get("expected_pmids", [])),
            expected_dois=tuple(str(d).lower() for d in raw.get("expected_dois", [])),
            notes=str(raw.get("notes", "")),
        )


@dataclass
class QueryResult:
    item: GoldSetItem
    retrieved_pmids: list[str]
    recall: dict[int, float]
    mrr: float


@dataclass
class AggregateMetrics:
    n_queries: int
    recall: dict[int, float]
    mrr: float


def load_goldset(path: Path) -> list[GoldSetItem]:
    """JSONL 골드셋을 로드한다. 빈 줄은 skip."""
    items: list[GoldSetItem] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: invalid JSON — {e}") from e
            items.append(GoldSetItem.from_dict(raw))
    return items


def recall_at_k(expected: Iterable[str], retrieved_pmids: list[str], k: int) -> float:
    """Set-based recall@k — 정답 중 top-k에 포함된 비율. (PMID-only 레거시)"""
    expected_set = {p for p in expected if p}
    if not expected_set:
        return 0.0
    top_k = set(retrieved_pmids[:k])
    return len(expected_set & top_k) / len(expected_set)


def _recall_at_k_union(expected_ids: set[str], retrieved_id_sets: list[set[str]], k: int) -> float:
    """PMID∪DOI union recall@k — 정답 PMID 또는 DOI 중 하나라도 매칭이면 hit."""
    if not expected_ids:
        return 0.0
    hits = 0
    for id_set in retrieved_id_sets[:k]:
        if expected_ids & id_set:
            hits += 1
    return min(hits, len(expected_ids)) / len(expected_ids)


def _mrr_union(expected_ids: set[str], retrieved_id_sets: list[set[str]]) -> float:
    """PMID∪DOI union MRR — 첫 hit의 역순위."""
    for rank, id_set in enumerate(retrieved_id_sets, start=1):
        if expected_ids & id_set:
            return 1.0 / rank
    return 0.0


def reciprocal_rank(expected: Iterable[str], retrieved_pmids: list[str]) -> float:
    """첫 정답 위치의 역수. 정답 없으면 0.0."""
    expected_set = {p for p in expected if p}
    if not expected_set:
        return 0.0
    for rank, pmid in enumerate(retrieved_pmids, start=1):
        if pmid in expected_set:
            return 1.0 / rank
    return 0.0


def evaluate_query(
    item: GoldSetItem,
    retriever: Retriever,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
    chunk_over_fetch: int = DEFAULT_CHUNK_OVER_FETCH,
) -> QueryResult:
    """단일 질의 평가. paper-level dedup (같은 PMID 중복 청크는 첫 위치만).

    chunk-level retriever에서 ``max(top_k_values) * chunk_over_fetch`` 만큼 over-fetch
    한 뒤 paper-level로 dedup 한다.
    """
    max_paper_k = max(top_k_values)
    chunks = retriever(item.query, max_paper_k * chunk_over_fetch)

    seen: set[str] = set()
    retrieved_pmids: list[str] = []
    retrieved_dois: list[str] = []
    for c in chunks:
        pmid = c.get("pmid") or c.get("paper_pmid") or ""
        doi = (c.get("doi") or c.get("paper_doi") or "").lower()
        paper_key = doi or pmid
        if not paper_key or paper_key in seen:
            continue
        seen.add(paper_key)
        if pmid:
            seen.add(pmid)
        if doi:
            seen.add(doi)
        retrieved_pmids.append(pmid)
        retrieved_dois.append(doi)

    expected_ids = {p for p in item.expected_pmids if p} | {d for d in item.expected_dois if d}
    retrieved_ids = []
    for pmid, doi in zip(retrieved_pmids, retrieved_dois, strict=True):
        ids = {pmid, doi} - {""}
        retrieved_ids.append(ids)

    recalls = {k: _recall_at_k_union(expected_ids, retrieved_ids, k) for k in top_k_values}
    mrr_val = _mrr_union(expected_ids, retrieved_ids)
    return QueryResult(item=item, retrieved_pmids=retrieved_pmids, recall=recalls, mrr=mrr_val)


def run_evaluation(
    goldset: list[GoldSetItem],
    retriever: Retriever,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
    chunk_over_fetch: int = DEFAULT_CHUNK_OVER_FETCH,
) -> list[QueryResult]:
    """골드셋 전체에 대해 평가. 개별 질의 실패는 로그 + skip."""
    results: list[QueryResult] = []
    for item in goldset:
        try:
            res = evaluate_query(item, retriever, top_k_values, chunk_over_fetch)
        except Exception:
            logger.exception("질의 평가 실패 id=%s", item.id)
            continue
        results.append(res)
    return results


def aggregate(
    results: list[QueryResult],
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
) -> AggregateMetrics:
    if not results:
        return AggregateMetrics(n_queries=0, recall=dict.fromkeys(top_k_values, 0.0), mrr=0.0)
    n = len(results)
    recalls = {k: sum(r.recall[k] for r in results) / n for k in top_k_values}
    mrr = sum(r.mrr for r in results) / n
    return AggregateMetrics(n_queries=n, recall=recalls, mrr=mrr)


def aggregate_by_category(
    results: list[QueryResult],
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
) -> dict[str, AggregateMetrics]:
    bucket: dict[str, list[QueryResult]] = defaultdict(list)
    for r in results:
        bucket[r.item.category].append(r)
    return {cat: aggregate(items, top_k_values) for cat, items in bucket.items()}


def render_report(
    overall: AggregateMetrics,
    per_category: dict[str, AggregateMetrics],
    goldset_path: Path,
    retriever_name: str,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
    timestamp: datetime | None = None,
) -> str:
    """Markdown 리포트 문자열을 생성한다."""
    ts = timestamp or datetime.now(tz=timezone.utc)
    k_headers = " | ".join(f"recall@{k}" for k in top_k_values)
    k_sep = " | ".join("---" for _ in top_k_values)

    lines: list[str] = [
        f"# RAG Retrieval 평가 리포트 ({ts.date()})",
        "",
        f"- 골드셋: `{goldset_path}` (n={overall.n_queries})",
        f"- Retriever: `{retriever_name}`",
        f"- 생성 시각 (UTC): {ts.isoformat(timespec='seconds')}",
        "",
        "## 전체 지표",
        "",
        f"| {k_headers} | MRR |",
        f"| {k_sep} | --- |",
    ]
    overall_cells = " | ".join(f"{overall.recall[k]:.3f}" for k in top_k_values)
    lines.append(f"| {overall_cells} | {overall.mrr:.3f} |")
    lines.append("")
    lines.append("## 카테고리별 지표")
    lines.append("")
    lines.append(f"| 카테고리 | n | {k_headers} | MRR |")
    lines.append(f"| --- | --- | {k_sep} | --- |")
    for cat in sorted(per_category.keys()):
        m = per_category[cat]
        cells = " | ".join(f"{m.recall[k]:.3f}" for k in top_k_values)
        lines.append(f"| {cat} | {m.n_queries} | {cells} | {m.mrr:.3f} |")
    lines.append("")
    return "\n".join(lines)


def _load_embeddings_jsonl(path: Path, expected_dim: int) -> tuple["np.ndarray", list[dict]]:
    """JSONL(.gz 허용) 임베딩 파일을 메모리 행렬 + 메타데이터로 로드한다.

    포맷: 각 줄은 chunk 메타 + ``embedding`` 키. ``embed_chunks_with_spec`` 결과를
    그대로 저장한 export_embeddings 산출물과 호환.

    Args:
        path: ``.jsonl`` 또는 ``.jsonl.gz`` 경로.
        expected_dim: 모든 줄의 ``embedding`` 길이가 이 값과 일치해야 한다.

    Returns:
        (matrix(N, dim) float32, metas[N]) — 정렬 보존.

    Raises:
        ValueError: malformed JSON 한 줄이라도, 또는 dim 불일치 한 줄이라도 발견 시.
            부분 적재된 상태로 진행하면 score 행렬과 metas 인덱스가 어긋난다.
    """
    import numpy as np

    opener = gzip.open if path.suffix == ".gz" else open
    vectors: list[list[float]] = []
    metas: list[dict] = []
    with opener(path, "rt", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no}: invalid JSON — {e}") from e
            if "embedding" not in raw:
                raise ValueError(f"{path}:{line_no}: missing 'embedding' key")
            emb = raw.pop("embedding")
            if not isinstance(emb, list) or len(emb) != expected_dim:
                raise ValueError(
                    f"{path}:{line_no}: embedding dim mismatch — expected {expected_dim}, got {len(emb) if isinstance(emb, list) else type(emb).__name__}"
                )
            vectors.append(emb)
            metas.append(raw)
    if not vectors:
        raise ValueError(f"{path}: 임베딩이 한 줄도 없음")
    matrix = np.asarray(vectors, dtype=np.float32)
    return matrix, metas


def _build_inmem_retriever(
    embeddings_path: Path,
    model_key: str,
) -> Retriever:
    """JSONL.gz에서 청크 메타+embedding 로드 → 메모리 cosine retrieval.

    모델별 dim이 달라도 Chroma 재적재 없이 즉시 검증 가능.
    `evidence_weight` 재정렬은 의도적 미반영 — 임베딩 순수 의미 비교에 한정한다.

    embedder의 `_model_cache`를 재사용하므로 test 모드에서 export 측이 이미 로드한
    SentenceTransformer 인스턴스가 그대로 query encoding에 쓰인다 (중복 적재 없음).
    """
    import numpy as np
    from mlops.pipeline.embedder import _get_model_by_spec
    from mlops.pipeline.specs import get_spec

    spec = get_spec(model_key)
    matrix, metas = _load_embeddings_jsonl(embeddings_path, expected_dim=spec.dim)

    # corpus가 spec.normalize=True로 export됐다는 전제 — 단위 벡터 가정.
    # 정규화되지 않은 벡터로 cosine을 계산하면 점수가 왜곡되어 A/B 비교가 부정확해진다.
    # export 산출물은 항상 정규화되어 있으므로 정상 경로에서는 이 분기에 도달하지 않는다.
    # 도달했다면 산출물이 손상된 것이므로 즉시 중단 — silent하게 잘못된 리포트를 만들지 않는다.
    if spec.normalize:
        norms = np.linalg.norm(matrix, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-3):
            raise ValueError(
                f"{embeddings_path}: corpus 벡터가 단위벡터가 아님 "
                f"(mean_norm={float(norms.mean()):.4f}). spec.normalize=True인데 export 산출물이 "
                "정규화되지 않은 상태입니다. cosine 점수가 왜곡되어 A/B 비교가 부정확해지므로 즉시 중단."
            )

    model = _get_model_by_spec(spec)

    def _retrieve(query: str, top_k: int) -> list[dict]:
        q_text = (spec.query_prefix + query) if spec.query_prefix else query
        qvec = model.encode(q_text, normalize_embeddings=spec.normalize)
        qvec_arr = np.asarray(qvec, dtype=np.float32)
        # 단위벡터 가정 시 cosine = dot product
        scores = matrix @ qvec_arr
        top_idx = np.argsort(scores)[::-1][:top_k]
        return [
            {
                "pmid": metas[i].get("paper_pmid", ""),
                "title": metas[i].get("paper_title", ""),
                "section": metas[i].get("section_name", ""),
                "score": float(scores[i]),
            }
            for i in top_idx
        ]

    return _retrieve


def _build_chroma_retriever() -> Retriever:
    """실제 ChromaDB 검색 retriever — 호출 시점에만 import (테스트에서는 monkeypatch)."""
    import os

    import chromadb
    from sentence_transformers import SentenceTransformer

    persist = os.environ.get("CHROMA_PERSIST_PATH", "/chroma-data")
    collection_name = os.environ.get("CHROMA_COLLECTION_NAME", "paper_chunks")
    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-large-en-v1.5")
    instruction = "Represent this sentence for searching relevant passages: "

    client = chromadb.PersistentClient(path=persist)
    collection = client.get_collection(collection_name)
    model = SentenceTransformer(model_name)

    def _retrieve(query: str, top_k: int) -> list[dict]:
        vec = model.encode(instruction + query).tolist()
        res = collection.query(
            query_embeddings=[vec],
            n_results=top_k,
            include=["metadatas", "distances"],
        )
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        return [
            {
                "pmid": (m or {}).get("paper_pmid", ""),
                "title": (m or {}).get("paper_title", ""),
                "section": (m or {}).get("section_name", ""),
                "score": float(1.0 - d),
            }
            for m, d in zip(metas, dists, strict=False)
        ]

    return _retrieve


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="RAG retrieval 자동 평가")
    parser.add_argument("--goldset", type=Path, required=True, help="JSONL 골드셋 경로")
    parser.add_argument("--output", type=Path, required=True, help="Markdown 리포트 출력 경로")
    parser.add_argument(
        "--top-k",
        type=int,
        nargs="+",
        default=list(DEFAULT_TOP_K_VALUES),
        help="recall@k 슬라이스 (default: 5 10)",
    )
    parser.add_argument(
        "--retriever-name",
        type=str,
        default=None,
        help="리포트에 기록할 retriever 식별자 (생략 시 retriever 모드에 따라 자동 결정)",
    )
    parser.add_argument(
        "--retriever",
        choices=["chroma", "inmem"],
        default="chroma",
        help="검색 백엔드. inmem=JSONL 직접 로드 cosine retriever (A/B 평가용)",
    )
    parser.add_argument(
        "--embeddings-file",
        type=Path,
        default=None,
        help="inmem retriever용 임베딩 JSONL(.gz) 경로 — --retriever=inmem 시 필수",
    )
    parser.add_argument(
        "--model-key",
        type=str,
        default=None,
        help="inmem retriever용 모델 key (registry 등록값) — --retriever=inmem 시 필수",
    )
    args = parser.parse_args(argv)

    if args.retriever == "inmem":
        if args.embeddings_file is None or args.model_key is None:
            parser.error("--retriever=inmem 은 --embeddings-file 과 --model-key 가 필요합니다")
        if not args.embeddings_file.exists():
            parser.error(f"--embeddings-file 경로 없음: {args.embeddings_file}")

    top_k_values = tuple(sorted(set(args.top_k)))

    goldset = load_goldset(args.goldset)
    if not goldset:
        logger.error("골드셋이 비어있다: %s", args.goldset)
        return 1
    logger.info("골드셋 로드 완료 n=%d", len(goldset))

    if args.retriever == "inmem":
        retriever = _build_inmem_retriever(args.embeddings_file, args.model_key)
        retriever_name = args.retriever_name or f"inmem+{args.model_key}"
    else:
        retriever = _build_chroma_retriever()
        retriever_name = args.retriever_name or "chroma+bge-large-en-v1.5"

    results = run_evaluation(goldset, retriever, top_k_values)
    overall = aggregate(results, top_k_values)
    per_cat = aggregate_by_category(results, top_k_values)

    report = render_report(
        overall=overall,
        per_category=per_cat,
        goldset_path=args.goldset,
        retriever_name=retriever_name,
        top_k_values=top_k_values,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    logger.info("리포트 작성: %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
