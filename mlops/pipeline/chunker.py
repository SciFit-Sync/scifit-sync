"""Section-Aware 논문 청킹 모듈.

설계 기준 (CLAUDE.md §2):
  - 청크 크기: 300~512 토큰
  - 오버랩: 50 토큰
  - 섹션 경계 존중: 섹션이 512 토큰 이하이면 분할하지 않음
  - 작은 섹션 누적 병합: JATS 등 깊이 중첩 <sec>가 작은 섹션을 양산하는 경우,
    인접 섹션을 MIN(300) 토큰 이상이 될 때까지 누적해 한 청크로 emit
  - 분할 잔여 흡수: 큰 섹션 분할 시 마지막 잔여 청크가 MIN/2 미만이면 직전 청크에 흡수
  - 토큰 카운트: tiktoken (cl100k_base)
"""

import logging

import tiktoken
from mlops.pipeline.config import CHUNK_MAX_TOKENS, CHUNK_MIN_TOKENS, CHUNK_OVERLAP_TOKENS
from mlops.pipeline.models import Chunk, PaperFull

logger = logging.getLogger(__name__)

_encoder: tiktoken.Encoding | None = None

# 분할 잔여 청크가 이 토큰 수 미만이면 직전 청크에 흡수한다.
_ABSORB_TAIL_BELOW = CHUNK_MIN_TOKENS // 2  # =150 (CHUNK_MIN_TOKENS=300 기준)
# 병합된 섹션명 메타가 너무 길어지지 않게 truncate 한다.
_SECTION_NAME_MAX_LEN = 80


def _get_encoder() -> tiktoken.Encoding:
    """tiktoken 인코더를 싱글턴으로 반환한다."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """텍스트의 토큰 수를 반환한다."""
    return len(_get_encoder().encode(text))


def _split_text_by_tokens(
    text: str,
    max_tokens: int = CHUNK_MAX_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """텍스트를 토큰 기준으로 분할한다 (overlap 포함).

    문장 경계를 최대한 존중하되, 불가능하면 토큰 단위로 자른다.
    마지막 청크 emit 후엔 즉시 break 해 잔여 토큰을 미니 청크로 반복 emit하지 않는다.
    """
    encoder = _get_encoder()
    tokens = encoder.encode(text)

    if len(tokens) <= max_tokens:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunk_text = encoder.decode(chunk_tokens)

        is_last = end >= len(tokens)
        if not is_last:
            chunk_text = _adjust_to_sentence_boundary(chunk_text, encoder, max_tokens)

        chunks.append(chunk_text.strip())

        # 마지막 청크면 즉시 종료 — re-encode 라운드트립으로 인한 작은 advance가
        # 반복 루프를 만들지 않도록 함 (옛 버그: 잔여 토큰 영역을 50토큰씩 수십 번 emit)
        if is_last:
            break

        # 다음 시작점: 실제 사용된 토큰 수 - overlap. 최소 한 토큰은 전진.
        actual_tokens = len(encoder.encode(chunk_text))
        start += max(actual_tokens - overlap_tokens, 1)

    return [c for c in chunks if c]


def _adjust_to_sentence_boundary(text: str, encoder: tiktoken.Encoding, max_tokens: int) -> str:
    """청크 끝을 문장 경계(마침표)에 맞추되, 최소 토큰 수를 보장한다."""
    # 마지막 마침표 위치 찾기
    for sep in [". ", ".\n", "? ", "! "]:
        last_idx = text.rfind(sep)
        if last_idx > 0:
            candidate = text[: last_idx + 1]
            candidate_tokens = len(encoder.encode(candidate))
            # 최소 토큰 수의 절반은 유지
            if candidate_tokens >= max_tokens // 2:
                return candidate

    return text


def _merge_section_names(names: list[str]) -> str:
    """병합된 섹션명을 ' / '로 합치고 길이 제한한다.

    중복 제거 + 순서 보존. 너무 길면 truncate.
    """
    seen: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.append(n)
    joined = " / ".join(seen) if seen else "Untitled"
    if len(joined) > _SECTION_NAME_MAX_LEN:
        joined = joined[: _SECTION_NAME_MAX_LEN - 3] + "..."
    return joined


def _make_chunk(paper: PaperFull, idx: int, section_name: str, content: str, token_count: int) -> Chunk:
    return Chunk(
        paper_pmid=paper.meta.pmid,
        paper_title=paper.meta.title,
        section_name=section_name,
        chunk_index=idx,
        content=content,
        token_count=token_count,
        search_categories=list(paper.meta.search_categories),
        paper_doi=paper.meta.doi,
        publication_types=list(paper.meta.publication_types),
        evidence_weight=paper.meta.evidence_weight,
        fulltext_source=paper.meta.fulltext_source,
        published_year=paper.meta.published_year,
    )


def _absorb_into_previous(chunks: list[Chunk], extra_content: str) -> None:
    """직전 청크에 extra_content를 흡수한다 (Pydantic model_copy 사용)."""
    last = chunks[-1]
    merged = last.content + "\n\n" + extra_content
    chunks[-1] = last.model_copy(update={"content": merged, "token_count": count_tokens(merged)})


def chunk_paper(paper: PaperFull) -> list[Chunk]:
    """논문 1편을 Section-Aware + 작은 섹션 누적 머저 방식으로 청킹한다.

    전략:
    1. 본문 섹션이 없으면 폐기 (초록 fallback 없음)
    2. 각 섹션에 대해:
       - MAX 이상이면: 현재 버퍼 flush 후 _split_text_by_tokens로 분할,
         마지막 잔여(< MIN/2)는 직전 청크에 흡수
       - MAX 미만이면 버퍼에 누적:
         - 버퍼 + 현 섹션이 MAX 초과면 먼저 flush 후 현 섹션부터 새 버퍼
         - 버퍼가 MIN 이상이면 flush
    3. 끝나면 남은 버퍼 flush (작으면 직전 청크에 흡수)
    """
    if not paper.sections:
        logger.debug(
            "본문 없음 폐기: doi=%s pmid=%s",
            paper.meta.doi,
            paper.meta.pmid,
        )
        return []

    chunks: list[Chunk] = []
    buf_names: list[str] = []
    buf_contents: list[str] = []
    buf_tokens = 0

    def flush_buffer(allow_absorb: bool = False) -> None:
        """현재 버퍼를 emit. allow_absorb=True면 작은 잔여는 직전 청크에 흡수."""
        nonlocal buf_names, buf_contents, buf_tokens
        if not buf_contents:
            return
        merged_content = "\n\n".join(buf_contents)
        tc = count_tokens(merged_content)
        if allow_absorb and tc < _ABSORB_TAIL_BELOW and chunks:
            _absorb_into_previous(chunks, merged_content)
        else:
            chunks.append(
                _make_chunk(
                    paper,
                    idx=len(chunks),
                    section_name=_merge_section_names(buf_names),
                    content=merged_content,
                    token_count=tc,
                )
            )
        buf_names = []
        buf_contents = []
        buf_tokens = 0

    for section in paper.sections:
        name = section.name or "Untitled"
        content = (section.content or "").strip()
        if not content:
            continue
        tc = count_tokens(content)

        if tc >= CHUNK_MAX_TOKENS:
            # 단일 섹션이 MAX 이상 → 버퍼 비우고 split
            flush_buffer()
            sub_texts = _split_text_by_tokens(content, CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS)
            last_idx = len(sub_texts) - 1
            for j, sub in enumerate(sub_texts):
                sub_tc = count_tokens(sub)
                # 마지막 잔여가 너무 작으면 직전 청크에 흡수
                if j == last_idx and sub_tc < _ABSORB_TAIL_BELOW and chunks:
                    _absorb_into_previous(chunks, sub)
                else:
                    chunks.append(
                        _make_chunk(
                            paper,
                            idx=len(chunks),
                            section_name=name,
                            content=sub,
                            token_count=sub_tc,
                        )
                    )
            continue

        # 섹션이 MAX 미만 — 버퍼 누적 전 오버플로 체크
        if buf_tokens + tc > CHUNK_MAX_TOKENS:
            flush_buffer()

        buf_names.append(name)
        buf_contents.append(content)
        buf_tokens += tc

        # 버퍼가 MIN 이상이면 emit (다음 섹션을 새 청크로)
        if buf_tokens >= CHUNK_MIN_TOKENS:
            flush_buffer()

    # 마지막 잔여 버퍼 flush — 작으면 직전 청크에 흡수
    flush_buffer(allow_absorb=True)

    logger.debug(
        "청킹 완료: PMID=%s, 섹션=%d, 청크=%d (평균 %d토큰)",
        paper.meta.pmid,
        len(paper.sections),
        len(chunks),
        (sum(c.token_count for c in chunks) // len(chunks)) if chunks else 0,
    )
    return chunks


def chunk_papers(papers: list[PaperFull]) -> list[Chunk]:
    """복수 논문을 일괄 청킹한다."""
    all_chunks: list[Chunk] = []
    for paper in papers:
        chunks = chunk_paper(paper)
        all_chunks.extend(chunks)

    logger.info("전체 청킹 완료: 논문 %d편 → 청크 %d개", len(papers), len(all_chunks))
    return all_chunks
