"""OpenAlex 검색 어댑터 단위 테스트."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mlops.pipeline.openalex import (
    _RATE_LIMIT_BACKOFF_SCHEDULE,
    OpenAlexClient,
    _compute_backoff,
    _parse_retry_after,
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
    params = build_search_params(keywords=["x"], concept_ids=["C1"], per_page=25, mailto="a@b.com")
    assert "open_access.is_oa:true" in params["filter"]
    assert "language:en" in params["filter"]
    assert "type:article" in params["filter"]


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


def test_retry_on_5xx_eventually_succeeds(search_resp):
    """5xx에서 재시도하여 결국 성공."""
    from requests.exceptions import HTTPError

    client = OpenAlexClient(base_url="https://api.openalex.org", mailto="t@e.com", rate_limit=0)

    fail_resp = MagicMock()
    fail_resp.status_code = 503
    err = HTTPError("503")
    err.response = fail_resp
    fail_resp.raise_for_status.side_effect = err

    success_resp = MagicMock()
    success_resp.json.return_value = search_resp
    success_resp.raise_for_status = MagicMock()

    with patch("mlops.pipeline.openalex.requests.get", side_effect=[fail_resp, success_resp]):
        results = client.search(keywords=["x"], concept_ids=["C1"], max_results=10)

    assert len(results) == 1


def test_4xx_not_retried_raises():
    """404 등 4xx는 즉시 raise (재시도 X)."""
    from requests.exceptions import HTTPError

    client = OpenAlexClient(base_url="https://api.openalex.org", mailto="t@e.com", rate_limit=0)

    bad_resp = MagicMock()
    bad_resp.status_code = 400
    err = HTTPError("400")
    err.response = bad_resp
    bad_resp.raise_for_status.side_effect = err

    with patch("mlops.pipeline.openalex.requests.get", return_value=bad_resp), pytest.raises(HTTPError):
        client.search(keywords=["x"], concept_ids=["C1"], max_results=10)


def test_cursor_stuck_terminates_loop(search_resp):
    """next_cursor가 같은 값으로 반복되면 종료 (무한루프 방지)."""
    client = OpenAlexClient(base_url="https://api.openalex.org", mailto="t@e.com", rate_limit=0)

    stuck_resp = dict(search_resp)
    stuck_resp["meta"] = {"next_cursor": "samecursor"}

    mock_resp = MagicMock()
    mock_resp.json.return_value = stuck_resp
    mock_resp.raise_for_status = MagicMock()

    with patch("mlops.pipeline.openalex.requests.get", return_value=mock_resp) as mock_get:
        client.search(keywords=["x"], concept_ids=["C1"], max_results=1000)

    # 첫 호출 (cursor=*) + 두 번째 호출 (cursor=samecursor) → 세 번째에서 stuck 감지하고 종료
    assert mock_get.call_count == 2


def test_parse_retry_after_parses_delta_seconds():
    resp = MagicMock()
    resp.headers = {"Retry-After": "30"}
    assert _parse_retry_after(resp) == 30.0


def test_parse_retry_after_returns_none_for_missing_header():
    resp = MagicMock()
    resp.headers = {}
    assert _parse_retry_after(resp) is None


def test_parse_retry_after_returns_none_for_non_numeric():
    """HTTP-date 형식(Wed, 21 Oct...)이나 잘못된 값은 None 반환 → 스케줄 백오프 사용."""
    resp = MagicMock()
    resp.headers = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
    assert _parse_retry_after(resp) is None


def test_parse_retry_after_caps_unreasonable_value():
    """서버가 비정상적으로 큰 값을 보내도 상한 적용."""
    resp = MagicMock()
    resp.headers = {"Retry-After": "9999"}
    assert _parse_retry_after(resp) == 120.0


def test_compute_backoff_uses_schedule_for_429_without_retry_after():
    assert _compute_backoff(1, is_rate_limit=True, rate_limit=0.5, retry_after=None) == _RATE_LIMIT_BACKOFF_SCHEDULE[0]
    assert _compute_backoff(3, is_rate_limit=True, rate_limit=0.5, retry_after=None) == _RATE_LIMIT_BACKOFF_SCHEDULE[2]


def test_compute_backoff_retry_after_overrides_schedule():
    assert _compute_backoff(1, is_rate_limit=True, rate_limit=0.5, retry_after=42.0) == 42.0


def test_compute_backoff_exponential_for_transient():
    """5xx/transient는 기존 지수 백오프 유지 (0.5 × 2^1 = 1.0)."""
    assert _compute_backoff(1, is_rate_limit=False, rate_limit=0.5, retry_after=None) == 1.0


def test_compute_backoff_schedule_attempt_index_clamped():
    """attempt가 스케줄 길이를 초과해도 마지막 값을 반환."""
    last = _RATE_LIMIT_BACKOFF_SCHEDULE[-1]
    assert _compute_backoff(99, is_rate_limit=True, rate_limit=0.5, retry_after=None) == last


def test_429_retry_uses_rate_limit_backoff_schedule(search_resp):
    """429 응답이 들어오면 _compute_backoff(is_rate_limit=True) 경로로 sleep 호출."""
    from requests.exceptions import HTTPError

    client = OpenAlexClient(base_url="https://api.openalex.org", mailto="t@e.com", rate_limit=0)

    fail_resp = MagicMock()
    fail_resp.status_code = 429
    fail_resp.headers = {}  # Retry-After 없음 → 스케줄 사용
    err = HTTPError("429")
    err.response = fail_resp
    fail_resp.raise_for_status.side_effect = err

    ok_resp = MagicMock()
    ok_resp.json.return_value = search_resp
    ok_resp.raise_for_status = MagicMock()

    with (
        patch("mlops.pipeline.openalex.time.sleep") as mock_sleep,
        patch("mlops.pipeline.openalex.requests.get", side_effect=[fail_resp, ok_resp]),
    ):
        results = client.search(keywords=["x"], concept_ids=["C1"], max_results=10)

    assert len(results) == 1
    # rate_limit=0 초기 sleep + 1회 재시도 백오프 = 2회 sleep
    sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
    assert sleep_args[0] == 0  # 초기 rate_limit
    assert sleep_args[1] == _RATE_LIMIT_BACKOFF_SCHEDULE[0]


def test_429_respects_retry_after_header(search_resp):
    """Retry-After 헤더 값이 스케줄보다 우선."""
    from requests.exceptions import HTTPError

    client = OpenAlexClient(base_url="https://api.openalex.org", mailto="t@e.com", rate_limit=0)

    fail_resp = MagicMock()
    fail_resp.status_code = 429
    fail_resp.headers = {"Retry-After": "7"}
    err = HTTPError("429")
    err.response = fail_resp
    fail_resp.raise_for_status.side_effect = err

    ok_resp = MagicMock()
    ok_resp.json.return_value = search_resp
    ok_resp.raise_for_status = MagicMock()

    with (
        patch("mlops.pipeline.openalex.time.sleep") as mock_sleep,
        patch("mlops.pipeline.openalex.requests.get", side_effect=[fail_resp, ok_resp]),
    ):
        client.search(keywords=["x"], concept_ids=["C1"], max_results=10)

    sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
    # 초기 rate_limit=0, 재시도 백오프=Retry-After=7
    assert sleep_args[1] == 7.0


def test_max_retries_default_allows_more_attempts(search_resp):
    """DEFAULT_MAX_RETRIES=5 → 4회 연속 실패 후 5번째에 성공해도 통과."""
    from requests.exceptions import HTTPError

    client = OpenAlexClient(base_url="https://api.openalex.org", mailto="t@e.com", rate_limit=0)

    fail_resp = MagicMock()
    fail_resp.status_code = 429
    fail_resp.headers = {}
    err = HTTPError("429")
    err.response = fail_resp
    fail_resp.raise_for_status.side_effect = err

    ok_resp = MagicMock()
    ok_resp.json.return_value = search_resp
    ok_resp.raise_for_status = MagicMock()

    with (
        patch("mlops.pipeline.openalex.time.sleep"),
        patch(
            "mlops.pipeline.openalex.requests.get",
            side_effect=[fail_resp, fail_resp, fail_resp, fail_resp, ok_resp],
        ),
    ):
        results = client.search(keywords=["x"], concept_ids=["C1"], max_results=10)

    assert len(results) == 1


def test_parse_work_handles_null_optional_fields():
    """primary_location/authorships/concepts/ids가 None인 work도 정상 파싱."""
    work = {
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1/x",
        "title": "T",
        "publication_year": 2020,
        "primary_location": None,
        "authorships": None,
        "ids": None,
        "abstract_inverted_index": None,
        "concepts": None,
        "publication_types": None,
    }
    meta = parse_work(work)
    assert meta is not None
    assert meta.doi == "10.1/x"
    assert meta.journal == ""
    assert meta.authors == ""
    assert meta.abstract == ""
    assert meta.publication_types == []
