"""OpenAlex 검색 어댑터 단위 테스트."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mlops.pipeline.openalex import (
    OpenAlexClient,
    abstract_from_inverted_index,
    build_search_params,
    parse_work,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def search_resp() -> dict:
    return json.loads((FIXTURE_DIR / "openalex_search_resp.json").read_text())


def test_build_search_params_includes_mailto():
    params = build_search_params(
        keywords=["resistance training", "volume"],
        concept_ids=["C2779017737"],
        per_page=200,
        mailto="test@example.com",
    )
    assert params["mailto"] == "test@example.com"
    assert params["per_page"] == 200
    assert "resistance training" in params["search"]
    assert "C2779017737" in params["filter"]


def test_build_search_params_filters_oa_and_lang():
    params = build_search_params(
        keywords=["x"], concept_ids=["C1"], per_page=25, mailto="a@b.com"
    )
    assert "is_oa:true" in params["filter"]
    assert "language:en" in params["filter"]
    assert "type:journal-article" in params["filter"]


def test_parse_work_extracts_doi_pmid_pmcid(search_resp):
    work = search_resp["results"][0]
    meta = parse_work(work)
    assert meta is not None
    assert meta.doi == "10.1519/JSC.0000000000003456"
    assert meta.pmid == "31034459"
    assert meta.pmcid == "PMC6520849"
    assert meta.openalex_id == "W2018473023"
    assert meta.title == "Effects of training volume on muscle hypertrophy"
    assert meta.published_year == 2019
    assert meta.journal == "Journal of Strength and Conditioning Research"
    assert "Schoenfeld B" in meta.authors


def test_parse_work_returns_none_when_no_doi(search_resp):
    work = search_resp["results"][1]
    meta = parse_work(work)
    assert meta is None


def test_abstract_from_inverted_index_reconstruction():
    inverted = {"Resistance": [0], "training": [1, 5], "studies": [2], "the": [3, 4]}
    reconstructed = abstract_from_inverted_index(inverted)
    assert reconstructed == "Resistance training studies the the training"


def test_abstract_from_empty_inverted_index_returns_empty():
    assert abstract_from_inverted_index({}) == ""


def test_client_search_returns_paper_metas(search_resp):
    client = OpenAlexClient(base_url="https://api.openalex.org", mailto="t@e.com", rate_limit=0)

    with patch("mlops.pipeline.openalex.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = search_resp
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        results = client.search(
            keywords=["resistance training"],
            concept_ids=["C2779017737"],
            max_results=10,
        )

    assert len(results) == 1
    assert results[0].doi == "10.1519/JSC.0000000000003456"


def test_client_search_handles_pagination(search_resp):
    """per_page 200 + max_results 400 → 2 페이지 호출."""
    client = OpenAlexClient(base_url="https://api.openalex.org", mailto="t@e.com", rate_limit=0)

    # 응답에 next_cursor 추가하여 페이지네이션 유발
    paginated_resp = dict(search_resp)
    paginated_resp["meta"] = dict(search_resp["meta"])
    paginated_resp["meta"]["next_cursor"] = "page2cursor"

    last_resp = dict(search_resp)
    last_resp["meta"] = dict(search_resp["meta"])
    last_resp["meta"]["next_cursor"] = None  # 끝

    responses = [paginated_resp, last_resp]
    call_count = {"n": 0}

    def mock_get_side_effect(*args, **kwargs):
        mock_resp = MagicMock()
        mock_resp.json.return_value = responses[min(call_count["n"], len(responses) - 1)]
        mock_resp.raise_for_status = MagicMock()
        call_count["n"] += 1
        return mock_resp

    with patch("mlops.pipeline.openalex.requests.get", side_effect=mock_get_side_effect) as mock_get:
        client.search(keywords=["x"], concept_ids=["C1"], max_results=400, per_page=200)
        # 첫 페이지(cursor=*) + 두 번째 페이지(cursor=page2cursor) → 2회
        assert mock_get.call_count == 2
