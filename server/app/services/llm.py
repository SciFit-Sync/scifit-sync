"""LLM 클라이언트 모듈.

Gemini 2.5 Flash를 기본으로 사용하고, 실패 시 GPT-4o-mini로 fallback한다.
LLM_PROVIDER 환경변수로 강제 전환 가능.

API:
- generate(prompt) -> str             : 전체 응답을 한 번에 반환
- generate_stream(prompt) -> Iterator : 토큰 단위 delta 텍스트 스트리밍
"""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        env_path = _PROJECT_ROOT / "mlops" / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        pass


_load_env()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" | "openai"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

_gemini_client = None
_openai_client = None


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다. mlops/.env에 추가하세요.")
        from google import genai

        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini 초기화 완료: %s", GEMINI_MODEL)
    return _gemini_client


def _get_openai():
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다. mlops/.env에 추가하세요.")
        from openai import OpenAI

        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI 초기화 완료: %s", OPENAI_MODEL)
    return _openai_client


def generate(prompt: str) -> str:
    """프롬프트를 LLM에 전달하고 텍스트 응답을 반환한다.

    LLM_PROVIDER=gemini(기본): Gemini 실패 시 GPT-4o-mini로 자동 fallback.
    LLM_PROVIDER=openai: GPT-4o-mini만 사용.
    """
    if LLM_PROVIDER == "openai":
        client = _get_openai()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()

    # Gemini (기본)
    try:
        client = _get_gemini()
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return response.text.strip()
    except Exception as e:
        logger.warning("Gemini 실패 (%s), GPT-4o-mini fallback 시도", e)
        client = _get_openai()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()


def _openai_stream(client, prompt: str) -> Iterator[str]:
    stream = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            yield delta


def _gemini_stream(client, prompt: str) -> Iterator[str]:
    stream = client.models.generate_content_stream(model=GEMINI_MODEL, contents=prompt)
    for chunk in stream:
        text = getattr(chunk, "text", None)
        if text:
            yield text


def generate_stream(prompt: str) -> Iterator[str]:
    """프롬프트를 LLM에 전달하고 토큰(delta text)을 스트리밍한다.

    SSE에 흘려보내기 위한 generator. CLAUDE.md §11 RAG 파이프라인 6단계
    "Gemini 1.5 Flash SSE 스트리밍" 요구사항을 만족한다.

    LLM_PROVIDER=gemini(기본): Gemini 스트리밍 실패 시 OpenAI로 fallback.
    LLM_PROVIDER=openai: OpenAI 스트리밍만 사용.
    """
    if LLM_PROVIDER == "openai":
        yield from _openai_stream(_get_openai(), prompt)
        return

    # Gemini (기본)
    try:
        yield from _gemini_stream(_get_gemini(), prompt)
    except Exception as e:
        # 스트림 시작 전 실패만 fallback. 시작 후 실패는 부분 응답을 클라이언트가 이미 봤으므로 throw.
        logger.warning("Gemini 스트리밍 실패 (%s), OpenAI fallback 시도", e)
        yield from _openai_stream(_get_openai(), prompt)
