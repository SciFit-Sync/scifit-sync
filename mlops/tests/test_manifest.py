"""manifest v2 schema 단위 테스트."""
import json
from pathlib import Path

from mlops.pipeline.manifest import MANIFEST_SCHEMA_VERSION, Manifest


def test_empty_manifest_initial_state(tmp_path: Path):
    """파일 없으면 빈 manifest로 시작한다."""
    path = tmp_path / "manifest.json"
    m = Manifest.load(path)
    assert m.papers == {}
    assert m.is_indexed("10.1234/xyz") is False


def test_record_success_then_skip(tmp_path: Path):
    """fulltext_source가 설정되면 다음 시도에서 skip된다."""
    path = tmp_path / "manifest.json"
    m = Manifest.load(path)
    m.record_attempt(
        doi="10.1234/xyz",
        pmid="12345",
        pmcid="PMC1",
        openalex_id="W1",
        fulltext_source="pmc",
        tried_sources=["pmc"],
    )
    m.save(path)

    m2 = Manifest.load(path)
    assert m2.is_indexed("10.1234/xyz") is True


def test_failed_paper_is_retry_candidate_when_new_source_added(tmp_path: Path):
    """fulltext_source=null이고 tried_sources에 없는 새 소스가 active면 retry 후보."""
    path = tmp_path / "manifest.json"
    m = Manifest.load(path)
    m.record_attempt(
        doi="10.1234/abc",
        pmid="67890",
        pmcid=None,
        openalex_id=None,
        fulltext_source=None,
        tried_sources=["pmc", "europepmc"],
    )
    m.save(path)

    m2 = Manifest.load(path)
    retry = m2.retry_candidates(active_sources={"pmc", "europepmc", "unpaywall"})
    assert "10.1234/abc" in retry


def test_failed_paper_skipped_when_no_new_source(tmp_path: Path):
    """모든 active source를 이미 시도했으면 skip."""
    path = tmp_path / "manifest.json"
    m = Manifest.load(path)
    m.record_attempt(
        doi="10.1234/def",
        pmid="11111",
        pmcid=None,
        openalex_id=None,
        fulltext_source=None,
        tried_sources=["pmc", "europepmc"],
    )
    m.save(path)

    m2 = Manifest.load(path)
    retry = m2.retry_candidates(active_sources={"pmc", "europepmc"})
    assert "10.1234/def" not in retry


def test_v1_manifest_ignored_clean_slate(tmp_path: Path):
    """v1 schema(pmids 리스트)는 무시하고 빈 v2로 시작."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"pmids": ["12345", "67890"], "count": 2}))

    m = Manifest.load(path)
    assert m.papers == {}


def test_persisted_schema_has_version_2(tmp_path: Path):
    """저장된 schema는 version=2 필드를 갖는다."""
    path = tmp_path / "manifest.json"
    m = Manifest.load(path)
    m.record_attempt(doi="10.1/x", pmid=None, pmcid=None, openalex_id=None,
                     fulltext_source="pmc", tried_sources=["pmc"])
    m.save(path)

    data = json.loads(path.read_text())
    assert data["version"] == 2
    assert "papers" in data
    assert "stats" in data


def test_stats_counts(tmp_path: Path):
    """stats는 total_attempted, indexed_count, no_fulltext_count를 카운트."""
    path = tmp_path / "manifest.json"
    m = Manifest.load(path)
    m.record_attempt(doi="10.1/a", pmid=None, pmcid=None, openalex_id=None,
                     fulltext_source="pmc", tried_sources=["pmc"])
    m.record_attempt(doi="10.1/b", pmid=None, pmcid=None, openalex_id=None,
                     fulltext_source="europepmc", tried_sources=["pmc", "europepmc"])
    m.record_attempt(doi="10.1/c", pmid=None, pmcid=None, openalex_id=None,
                     fulltext_source=None, tried_sources=["pmc", "europepmc"])
    m.save(path)

    data = json.loads(path.read_text())
    assert data["stats"]["total_attempted"] == 3
    assert data["stats"]["indexed_count"] == 2
    assert data["stats"]["no_fulltext_count"] == 1


def test_corrupt_json_clean_slate(tmp_path: Path):
    """파싱 실패 파일은 빈 manifest로 fallback."""
    path = tmp_path / "manifest.json"
    path.write_text("not json {{{")
    m = Manifest.load(path)
    assert m.papers == {}


def test_missing_last_tried_at_falls_back_gracefully(tmp_path: Path):
    """v2 schema인데 last_tried_at이 빠진 entry도 load 가능 (KeyError 방지)."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "version": MANIFEST_SCHEMA_VERSION,
        "papers": {
            "10.1/x": {
                "pmid": "1",
                "pmcid": None,
                "openalex_id": None,
                "fulltext_source": "pmc",
                "tried_sources": ["pmc"],
                "indexed_at": "2026-05-18T10:00:00Z",
                # last_tried_at 누락
            }
        },
        "stats": {},
    }))
    m = Manifest.load(path)
    assert "10.1/x" in m.papers
    # indexed_at으로 fallback
    assert m.papers["10.1/x"].last_tried_at == "2026-05-18T10:00:00Z"


def test_record_attempt_merges_tried_sources_and_preserves_ids(tmp_path: Path):
    """두 번 record_attempt 시 tried_sources union + pmid/pmcid/openalex_id 보존."""
    m = Manifest.load(tmp_path / "m.json")
    m.record_attempt(
        doi="10.1/x", pmid="111", pmcid=None, openalex_id=None,
        fulltext_source=None, tried_sources=["pmc"],
    )
    m.record_attempt(
        doi="10.1/x", pmid=None, pmcid="PMC9", openalex_id="W1",
        fulltext_source="europepmc", tried_sources=["europepmc"],
    )
    e = m.papers["10.1/x"]
    assert e.pmid == "111"
    assert e.pmcid == "PMC9"
    assert e.openalex_id == "W1"
    assert e.tried_sources == ["europepmc", "pmc"]
    assert e.fulltext_source == "europepmc"
    assert e.indexed_at is not None


def test_save_creates_parent_dir(tmp_path: Path):
    """존재하지 않는 부모 디렉토리도 자동 생성."""
    path = tmp_path / "nested" / "deep" / "manifest.json"
    m = Manifest()
    m.save(path)
    assert path.exists()
