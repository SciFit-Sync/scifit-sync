"""골드셋 라벨링 CLI 도구.

질의별로 후보 논문 5개의 제목+한국어 초록을 한 번에 보여주고
번호를 선택해 정답 PMID를 매핑한다.
중간에 종료해도 labels.jsonl에 저장된 것까지 보존되며, 재실행 시 이어서 진행한다.

사용법:
    python mlops/scripts/label_cli.py \
        --candidates mlops/eval/candidates.jsonl \
        --output mlops/eval/labels.jsonl

입력:
    1~5  — 해당 번호 논문 선택
    0    — 관련 논문 없음 (건너뜀)
    q    — 저장 후 종료
"""

import argparse
import json
import time
from pathlib import Path

import requests

PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ABSTRACT_MAX_CHARS = 400
_abstract_cache: dict[str, str] = {}


def fetch_abstract(pmid: str) -> str:
    if pmid in _abstract_cache:
        return _abstract_cache[pmid]
    try:
        resp = requests.get(
            PUBMED_FETCH_URL,
            params={"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"},
            timeout=10,
        )
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        abstract_lines = []
        in_abstract = False
        for line in lines:
            if line.strip().startswith("Abstract"):
                in_abstract = True
                continue
            if in_abstract:
                if line.strip() == "" and abstract_lines:
                    break
                abstract_lines.append(line.strip())
        abstract = " ".join(abstract_lines).strip() or " ".join(lines[3:]).strip()
        result = abstract[:ABSTRACT_MAX_CHARS] + ("..." if len(abstract) > ABSTRACT_MAX_CHARS else "")
        time.sleep(0.34)
    except Exception:
        result = "(초록을 가져오지 못했습니다)"
    _abstract_cache[pmid] = result
    return result


def translate_to_korean(text: str) -> str:
    try:
        from deep_translator import GoogleTranslator

        return GoogleTranslator(source="en", target="ko").translate(text)
    except Exception:
        return text


def load_candidates(path: Path) -> list[dict]:
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                items.append(json.loads(stripped))
    return items


def load_existing_labels(path: Path) -> set[str]:
    """이미 라벨링된 qid 집합 반환."""
    done = set()
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                rec = json.loads(stripped)
                done.add(rec["qid"])
    return done


def append_label(path: Path, qid: str, pmid: str | None) -> None:
    """pmid=None이면 관련 논문 없음으로 기록."""
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"qid": qid, "pmid": pmid}, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="골드셋 라벨링 CLI")
    parser.add_argument("--candidates", type=Path, default=Path("mlops/eval/candidates.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("mlops/eval/labels.jsonl"))
    args = parser.parse_args(argv)

    candidates = load_candidates(args.candidates)
    done = load_existing_labels(args.output)

    remaining = [item for item in candidates if item["id"] not in done]
    total = len(candidates)

    print("\n=== 골드셋 라벨링 ===")
    print(f"전체 {total}개 질의 중 {len(done)}개 완료, {len(remaining)}개 남음\n")
    print("입력: 1~5=논문 선택  0=없음  q=종료\n")

    for item in remaining:
        qid = item["id"]
        query_ko = item.get("query_ko", "")
        query_en = item["query"]
        category = item.get("category", "")
        cands = item["candidates"]
        print(f"\n{'=' * 60}")
        print(f"[{total - len(remaining) + remaining.index(item) + 1}/{total}] {qid} | {category}")
        print(f"  EN: {query_en}")
        if query_ko:
            print(f"  KO: {query_ko}")

        print(f"\n  초록 불러오는 중... (총 {len(cands)}개)")
        papers = []
        for i, cand in enumerate(cands, start=1):
            pmid = cand["pmid"]
            title = cand["title"]
            score = cand["score"]
            abstract = fetch_abstract(pmid)
            abstract_ko = translate_to_korean(abstract)
            papers.append((pmid, title, score, abstract_ko))
            print(f"  {i}/{len(cands)} 완료", end="\r")

        print()
        for i, (pmid, title, score, abstract_ko) in enumerate(papers, start=1):
            print(f"\n  [{i}] score={score}  PMID={pmid}")
            print(f"  제목: {title}")
            print(f"  초록: {abstract_ko}")

        print()
        while True:
            try:
                key = input(f"  선택 (1~{len(cands)} / 0=없음 / q=종료) > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n종료합니다.")
                return

            if key == "q":
                print("\n저장 후 종료합니다.")
                return
            elif key == "0":
                append_label(args.output, qid, None)
                print("  → 관련 논문 없음으로 기록")
                break
            elif key.isdigit() and 1 <= int(key) <= len(cands):
                idx = int(key) - 1
                selected_pmid = papers[idx][0]
                selected_title = papers[idx][1]
                append_label(args.output, qid, selected_pmid)
                print(f"  ✓ 선택: [{key}] {selected_title[:60]}")
                break
            else:
                print(f"  1~{len(cands)}, 0, q 중 하나를 입력하세요.")

    print("\n\n모든 라벨링 완료!")
    print(f"결과: {args.output}")


if __name__ == "__main__":
    main()
