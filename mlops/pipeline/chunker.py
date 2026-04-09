"""Section-Aware 논문 청킹 모듈.

설계 기준 (CLAUDE.md §2):
  - 청크 크기: 300~512 토큰
  - 오버랩: 50 토큰
  - 섹션 경계 존중: 섹션이 512 토큰 이하이면 분할하지 않음
  - 토큰 카운트: tiktoken (cl100k_base)
"""

import logging

import tiktoken
from mlops.pipeline.config import CHUNK_MAX_TOKENS, CHUNK_MIN_TOKENS, CHUNK_OVERLAP_TOKENS
from mlops.pipeline.models import Chunk, PaperFull

logger = logging.getLogger(__name__)

_encoder: tiktoken.Encoding | None = None


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

        # 문장 경계로 조정 (마지막 청크가 아닌 경우)
        if end < len(tokens):
            chunk_text = _adjust_to_sentence_boundary(chunk_text, encoder, max_tokens)

        chunks.append(chunk_text.strip())

        # 다음 시작점: 실제 사용된 토큰 수 - overlap
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


def chunk_paper(paper: PaperFull) -> list[Chunk]:
    """논문 1편을 Section-Aware 방식으로 청킹한다.

    전략:
    1. 전문 섹션이 있으면 섹션별로 청킹
    2. 전문이 없으면 초록을 청킹
    3. 섹션이 CHUNK_MAX_TOKENS 이하이면 분할하지 않음
    4. 섹션이 CHUNK_MAX_TOKENS 초과이면 overlap 50으로 분할
    """
    chunks: list[Chunk] = []
    chunk_idx = 0

    # 소스 텍스트 결정
    if paper.sections:
        text_units = [(s.name, s.content) for s in paper.sections]
    elif paper.meta.abstract:
        text_units = [("Abstract", paper.meta.abstract)]
    else:
        logger.debug("텍스트 없음: PMID=%s", paper.meta.pmid)
        return []

    for section_name, content in text_units:
        content = content.strip()
        if not content:
            continue

        token_count = count_tokens(content)

        # 최소 토큰 미만이면 건너뜀 (의미 있는 내용이 아닌 경우)
        if token_count < CHUNK_MIN_TOKENS // 3:
            continue

        # 섹션이 최대 토큰 이하이면 그대로 1개 청크
        if token_count <= CHUNK_MAX_TOKENS:
            chunks.append(
                Chunk(
                    paper_pmid=paper.meta.pmid,
                    paper_title=paper.meta.title,
                    section_name=section_name,
                    chunk_index=chunk_idx,
                    content=content,
                    token_count=token_count,
                )
            )
            chunk_idx += 1
        else:
            # 섹션이 크면 분할
            sub_texts = _split_text_by_tokens(content, CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS)
            for sub_text in sub_texts:
                tc = count_tokens(sub_text)
                chunks.append(
                    Chunk(
                        paper_pmid=paper.meta.pmid,
                        paper_title=paper.meta.title,
                        section_name=section_name,
                        chunk_index=chunk_idx,
                        content=sub_text,
                        token_count=tc,
                    )
                )
                chunk_idx += 1

    logger.debug(
        "청킹 완료: PMID=%s, 섹션=%d, 청크=%d",
        paper.meta.pmid,
        len(text_units),
        len(chunks),
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
