"""LLM 클라이언트 모듈.

Gemini 2.5 Flash를 기본으로 사용하고, 실패 시 GPT-4o-mini로 fallback한다.
LLM_PROVIDER 환경변수로 강제 전환 가능.
"""

import logging
import os
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
