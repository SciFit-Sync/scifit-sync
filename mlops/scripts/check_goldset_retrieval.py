"""골드셋 쿼리 → ChromaDB 검색 결과 확인 스크립트.

goldset_seed.jsonl의 각 쿼리를 ChromaDB에 검색하고
notes에 명시된 기대 논문이 상위 결과에 포함되는지 수동 확인용으로 출력한다.

실행 (GPU 서버):
    python -m mlops.scripts.check_goldset_retrieval \
        --seed mlops/eval/goldset_seed.jsonl \
        --top_k 10 \
        [--category hypertrophy] \
        [--query_id Q001]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server" / "app" / "services"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

from rag import search_chunks  # noqa: E402


def _load_seeds(path: Path, category: str | None, query_id: str | None) -> list[dict]:
    seeds = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            seed = json.loads(line)
            if category and seed.get("category") != category:
                continue
            if query_id and seed.get("id") != query_id:
                continue
            seeds.append(seed)
    return seeds


def run(seed_path: Path, top_k: int, category: str | None, query_id: str | None) -> None:
    seeds = _load_seeds(seed_path, category, query_id)
    if not seeds:
        print("해당하는 쿼리 없음.")
        return

    hit_count = 0
    total = len(seeds)

    for seed in seeds:
        qid = seed["id"]
        query = seed["query"]
        notes = seed.get("notes", "")
        expected = seed.get("expected_pmids", [])

        print(f"\n{'=' * 70}")
        print(f"[{qid}] {query}")
        if notes:
            print(f"  기대 논문: {notes}")
        if expected:
            print(f"  expected_pmids: {expected}")

        chunks = search_chunks(query, top_k=top_k)

        if not chunks:
            print("  검색 결과 없음 (threshold 미달 또는 corpus 부재)")
            continue

        print(f"\n  검색 결과 (top {len(chunks)}):")
        retrieved_pmids = set()
        for i, c in enumerate(chunks, 1):
            pmid = c.get("pmid", "")
            doi = c.get("doi", "")
            title = c.get("title", "")[:60]
            score = c.get("score", 0)
            retrieved_pmids.add(pmid)
            hit_marker = " ✓" if pmid in expected else ""
            print(f"    [{i}] score={score:.4f}  PMID={pmid or '-'}  DOI={doi or '-'}{hit_marker}")
            print(f"         {title}")

        if expected:
            hits = set(expected) & retrieved_pmids
            miss = set(expected) - retrieved_pmids
            print(f"\n  Hit: {len(hits)}/{len(expected)}  |  Miss: {sorted(miss) or '없음'}")
            if hits:
                hit_count += 1

    if total > 0:
        coverage = hit_count / total * 100
        print(f"\n{'=' * 70}")
        print(f"전체 {total}개 쿼리 중 expected_pmids 있는 쿼리 hit율: {coverage:.1f}%")
        print("(expected_pmids가 비어있는 쿼리는 수동으로 결과 확인 필요)")


def main() -> None:
    parser = argparse.ArgumentParser(description="골드셋 쿼리 검색 결과 확인")
    parser.add_argument("--seed", type=Path, default=Path("mlops/eval/goldset_seed.jsonl"))
    parser.add_argument("--top_k", type=int, default=10)
    parser.add_argument("--category", type=str, default=None, help="hypertrophy | strength | endurance 등")
    parser.add_argument("--query_id", type=str, default=None, help="특정 쿼리 ID (예: Q001)")
    args = parser.parse_args()
    run(args.seed, args.top_k, args.category, args.query_id)


if __name__ == "__main__":
    main()
