"""build_goldset 단위 테스트."""

import json

import pytest
from mlops.scripts.build_goldset import (
    build_goldset_entry,
    classify_paper,
    run,
)


class TestClassifyPaper:
    def test_matchable(self):
        paper = {"indexed": True, "resolved_pmid": "12345", "failure_reason": None}
        assert classify_paper(paper) == "matchable"

    def test_indexed_but_no_pmid(self):
        # spec §4.3: resolved_pmid == "" 면 indexed 값과 무관하게 no_pmid
        # (DOI-only paper that got into corpus but can't be matched by evaluator)
        paper = {"indexed": True, "resolved_pmid": "", "failure_reason": None}
        assert classify_paper(paper) == "no_pmid"

    def test_no_pmid_with_indexed_false(self):
        # spec §4.3: resolved_pmid == "" 면 indexed=False여도 no_pmid
        paper = {"indexed": False, "resolved_pmid": "", "failure_reason": "no_pmid_from_openalex"}
        assert classify_paper(paper) == "no_pmid"

    def test_failed(self):
        paper = {"indexed": False, "resolved_pmid": "12345", "failure_reason": "no_fulltext"}
        assert classify_paper(paper) == "failed"

    def test_no_pmid(self):
        paper = {"indexed": False, "resolved_pmid": "", "failure_reason": "no_pmid_from_openalex"}
        assert classify_paper(paper) == "no_pmid"


class TestBuildGoldsetEntry:
    def test_emits_matchable_set(self):
        seed = {
            "id": "Q001",
            "query": "test",
            "query_ko": "테스트",
            "category": "hypertrophy",
            "fitness_goals": ["hypertrophy"],
            "used_in": ["routine_generation"],
            "expected_pmids": [],
            "notes": "",
        }
        q_prov = {
            "category": "hypertrophy",
            "papers": [
                {
                    "raw_id": "PMID:1",
                    "resolved_pmid": "1",
                    "indexed": True,
                    "failure_reason": None,
                    "resolved_doi": "10.1/a",
                },
                {
                    "raw_id": "PMID:2",
                    "resolved_pmid": "2",
                    "indexed": False,
                    "failure_reason": "no_fulltext",
                    "resolved_doi": "10.1/b",
                },
                {
                    "raw_id": "DOI:10.1/c",
                    "resolved_pmid": "",
                    "indexed": False,
                    "failure_reason": "no_pmid_from_openalex",
                    "resolved_doi": "10.1/c",
                },
            ],
        }
        entry = build_goldset_entry(seed, q_prov)
        assert entry["expected_pmids"] == ["1"]
        assert entry["curated_pmids_all"] == ["1", "2"]  # PMID 없는 c는 제외
        assert len(entry["papers_failed"]) == 2  # b (no_fulltext), c (no_pmid_from_openalex)
        assert entry["corpus_coverage"] == 0.5

    def test_returns_none_for_empty_matchable(self):
        """Method B: empty expected_pmids는 goldset entry 생성 안 함."""
        seed = {"id": "Q002", "query": "x", "expected_pmids": []}
        q_prov = {
            "category": "x",
            "papers": [
                {
                    "raw_id": "PMID:1",
                    "resolved_pmid": "1",
                    "indexed": False,
                    "failure_reason": "no_fulltext",
                    "resolved_doi": "10.1/a",
                },
            ],
        }
        entry = build_goldset_entry(seed, q_prov)
        assert entry is None


class TestRunIntegration:
    """run() integration test: provenance fixture → goldset.jsonl + summary."""

    def _make_provenance(self) -> dict:
        return {
            "Q001": {
                "category": "hypertrophy",
                "papers": [
                    {
                        "raw_id": "PMID:1",
                        "resolved_pmid": "1",
                        "indexed": True,
                        "failure_reason": None,
                        "resolved_doi": "10.1/a",
                    },
                    {
                        "raw_id": "PMID:2",
                        "resolved_pmid": "2",
                        "indexed": False,
                        "failure_reason": "no_fulltext",
                        "resolved_doi": "10.1/b",
                    },
                ],
            },
            "Q002": {
                "category": "strength",
                "papers": [
                    {
                        "raw_id": "PMID:3",
                        "resolved_pmid": "3",
                        "indexed": True,
                        "failure_reason": None,
                        "resolved_doi": "10.1/c",
                    },
                ],
            },
            # Q003 is in seed but NOT in provenance → unlabeled
        }

    def _make_seed(self) -> list[dict]:
        return [
            {
                "id": "Q001",
                "query": "vol query",
                "query_ko": "볼륨",
                "category": "hypertrophy",
                "fitness_goals": ["hypertrophy"],
                "used_in": ["routine_generation"],
                "expected_pmids": [],
                "notes": "",
            },
            {
                "id": "Q002",
                "query": "strength query",
                "query_ko": "강도",
                "category": "strength",
                "fitness_goals": ["strength"],
                "used_in": ["routine_generation"],
                "expected_pmids": [],
                "notes": "",
            },
            {
                "id": "Q003",
                "query": "rest query",
                "query_ko": "휴식",
                "category": "hypertrophy",
                "fitness_goals": ["hypertrophy"],
                "used_in": ["routine_generation"],
                "expected_pmids": [],
                "notes": "",
            },
        ]

    def test_run_creates_goldset_jsonl(self, tmp_path):
        prov_path = tmp_path / "provenance.json"
        prov_path.write_text(json.dumps(self._make_provenance()), encoding="utf-8")

        seed_path = tmp_path / "seed.jsonl"
        with open(seed_path, "w", encoding="utf-8") as f:
            for s in self._make_seed():
                f.write(json.dumps(s) + "\n")

        goldset_path = tmp_path / "goldset.jsonl"
        summary_path = tmp_path / "reports" / "summary.md"

        run(seed_path, prov_path, goldset_path, summary_path)

        assert goldset_path.exists()
        entries = [json.loads(line) for line in goldset_path.read_text().strip().splitlines()]
        # Q001 and Q002 have matchable papers, Q003 is unlabeled
        assert len(entries) == 2
        ids = {e["id"] for e in entries}
        assert "Q001" in ids
        assert "Q002" in ids
        assert "Q003" not in ids

    def test_run_summary_counts(self, tmp_path):
        prov_path = tmp_path / "provenance.json"
        prov_path.write_text(json.dumps(self._make_provenance()), encoding="utf-8")

        seed_path = tmp_path / "seed.jsonl"
        with open(seed_path, "w", encoding="utf-8") as f:
            for s in self._make_seed():
                f.write(json.dumps(s) + "\n")

        goldset_path = tmp_path / "goldset.jsonl"
        summary_path = tmp_path / "reports" / "summary.md"

        run(seed_path, prov_path, goldset_path, summary_path)

        assert summary_path.exists()
        summary = summary_path.read_text()
        assert "metrics_eligible_queries: 2" in summary
        assert "unlabeled_queries: 1" in summary

    def test_run_corpus_gap_vs_unlabeled(self, tmp_path):
        """Q with failed-only papers → corpus_gap. Q not in provenance → unlabeled."""
        provenance = {
            "Q001": {
                "category": "hypertrophy",
                "papers": [
                    # failed but has resolved_pmid → corpus_gap
                    {
                        "raw_id": "PMID:1",
                        "resolved_pmid": "1",
                        "indexed": False,
                        "failure_reason": "no_fulltext",
                        "resolved_doi": "10.1/a",
                    },
                ],
            },
            # Q002 absent → unlabeled
        }
        seed = [
            {
                "id": "Q001",
                "query": "vol",
                "query_ko": "볼",
                "category": "hypertrophy",
                "fitness_goals": ["hypertrophy"],
                "used_in": ["routine_generation"],
                "expected_pmids": [],
                "notes": "",
            },
            {
                "id": "Q002",
                "query": "rest",
                "query_ko": "휴",
                "category": "hypertrophy",
                "fitness_goals": ["hypertrophy"],
                "used_in": ["routine_generation"],
                "expected_pmids": [],
                "notes": "",
            },
        ]
        prov_path = tmp_path / "provenance.json"
        prov_path.write_text(json.dumps(provenance), encoding="utf-8")
        seed_path = tmp_path / "seed.jsonl"
        with open(seed_path, "w", encoding="utf-8") as f:
            for s in seed:
                f.write(json.dumps(s) + "\n")

        goldset_path = tmp_path / "goldset.jsonl"
        summary_path = tmp_path / "reports" / "summary.md"
        run(seed_path, prov_path, goldset_path, summary_path)

        summary = summary_path.read_text()
        assert "metrics_eligible_queries: 0" in summary
        assert "corpus_gap_queries: 1" in summary
        assert "unlabeled_queries: 1" in summary

    def test_run_expected_pmids_field(self, tmp_path):
        """goldset entry의 expected_pmids는 matchable paper의 PMID만 포함."""
        provenance = {
            "Q001": {
                "category": "hypertrophy",
                "papers": [
                    {
                        "raw_id": "PMID:10",
                        "resolved_pmid": "10",
                        "indexed": True,
                        "failure_reason": None,
                        "resolved_doi": "10.1/x",
                    },
                    {
                        "raw_id": "PMID:20",
                        "resolved_pmid": "20",
                        "indexed": True,
                        "failure_reason": None,
                        "resolved_doi": "10.1/y",
                    },
                    {
                        "raw_id": "PMID:30",
                        "resolved_pmid": "30",
                        "indexed": False,
                        "failure_reason": "no_fulltext",
                        "resolved_doi": "10.1/z",
                    },
                ],
            },
        }
        seed = [
            {
                "id": "Q001",
                "query": "x",
                "query_ko": "x",
                "category": "hypertrophy",
                "fitness_goals": ["hypertrophy"],
                "used_in": ["routine_generation"],
                "expected_pmids": [],
                "notes": "",
            }
        ]
        prov_path = tmp_path / "provenance.json"
        prov_path.write_text(json.dumps(provenance), encoding="utf-8")
        seed_path = tmp_path / "seed.jsonl"
        with open(seed_path, "w", encoding="utf-8") as f:
            for s in seed:
                f.write(json.dumps(s) + "\n")

        goldset_path = tmp_path / "goldset.jsonl"
        summary_path = tmp_path / "reports" / "summary.md"
        run(seed_path, prov_path, goldset_path, summary_path)

        entries = [json.loads(line) for line in goldset_path.read_text().strip().splitlines()]
        assert len(entries) == 1
        entry = entries[0]
        assert sorted(entry["expected_pmids"]) == ["10", "20"]
        assert sorted(entry["curated_pmids_all"]) == ["10", "20", "30"]
        assert entry["corpus_coverage"] == pytest.approx(2 / 3, abs=0.001)
