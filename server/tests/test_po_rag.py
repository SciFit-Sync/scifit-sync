import asyncio
import pytest
from unittest.mock import AsyncMock, patch

SAMPLE_CHUNKS = [
    {"document": "Studies show 5% load increment per session improves strength.", "similarity": 0.85, "score": 0.85}
]


@pytest.fixture(autouse=True)
def clear_cache():
    from app.services import po_rag
    po_rag._cache.clear()
    yield
    po_rag._cache.clear()


class TestConvertToKg:
    def test_basic_conversion(self):
        from app.services.po_rag import _convert_to_kg
        assert _convert_to_kg(5.0, 100.0) == 5.0

    def test_rounds_to_nearest_2_5(self):
        from app.services.po_rag import _convert_to_kg
        assert _convert_to_kg(3.0, 100.0) == 2.5

    def test_min_clamp(self):
        from app.services.po_rag import _convert_to_kg
        assert _convert_to_kg(0.1, 10.0) == 1.25

    def test_max_clamp(self):
        from app.services.po_rag import _convert_to_kg
        assert _convert_to_kg(50.0, 100.0) == 10.0


class TestRagPoIncrement:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_none_when_no_chunks(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=[])):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None

    def test_returns_none_when_llm_returns_null(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": null}')):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None

    def test_converts_percent_to_kg(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": 5}')):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result == 5.0

    def test_returns_none_when_1rm_is_none(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": 5}')):
            result = self._run(rag_po_increment("hypertrophy", "cable", None))
        assert result is None

    def test_cache_hit_skips_rag_and_llm(self):
        from app.services.po_rag import rag_po_increment, _cache_set
        _cache_set("hypertrophy", "cable", 5.0)
        with patch("app.services.po_rag._call_search_async", new=AsyncMock()) as mock_search, \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock()) as mock_llm:
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
            mock_search.assert_not_called()
            mock_llm.assert_not_called()
        assert result == 5.0

    def test_cache_hit_with_none_pct_returns_none(self):
        from app.services.po_rag import rag_po_increment, _cache_set
        _cache_set("hypertrophy", "cable", None)
        with patch("app.services.po_rag._call_search_async", new=AsyncMock()) as mock_search:
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
            mock_search.assert_not_called()
        assert result is None

    def test_chroma_exception_returns_none(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(side_effect=RuntimeError("chroma down"))):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None

    def test_invalid_json_returns_none(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value="not valid json")):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None

    def test_non_numeric_pct_returns_none(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": "five"}')):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None
