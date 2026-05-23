"""parse_curated_papers 단위 테스트."""
import json
from pathlib import Path

import pytest

from mlops.scripts.parse_curated_papers import (
    extract_ids_from_lines,
    parse_papers_txt,
    detect_issues,
)


SAMPLE_TXT = """Hypertrophy
Q001: What is the optimal weekly set volume?
1. DOI: 10.1080/02640414.2016.1210197
2. PMID: 35291645 PMCID: PMC8884877 DOI: 10.2478/hukin-2022-0017
3. PMID 20512950

Q004 삭제

Q027: Concurrent gains
1. DOI: 10.1007/s40279-026-02401-y
2. DOI: 10.1519/JSC.0000000000004304
"""


class TestExtractIdsFromLines:
    def test_extracts_pmid_with_label(self):
        lines = ["PMID: 35291645 DOI: 10.2478/hukin-2022-0017"]
        pmids, pmcids, dois = extract_ids_from_lines(lines)
        assert "35291645" in pmids
        assert "10.2478/hukin-2022-0017" in dois

    def test_extracts_pmid_without_colon(self):
        lines = ["3. PMID 20512950"]
        pmids, _, _ = extract_ids_from_lines(lines)
        assert "20512950" in pmids

    def test_extracts_pmcid(self):
        lines = ["PMCID: PMC8884877"]
        _, pmcids, _ = extract_ids_from_lines(lines)
        assert "PMC8884877" in pmcids

    def test_dedup_within_lines(self):
        lines = ["DOI: 10.1080/test", "DOI: 10.1080/test"]
        _, _, dois = extract_ids_from_lines(lines)
        assert dois.count("10.1080/test") == 1


class TestDetectIssues:
    def test_detects_placeholder_doi(self):
        issues = detect_issues(["10.1001/jamanetworkopen.2024.xxxx"], [], "Q039")
        assert len(issues["placeholder_doi"]) == 1
        assert issues["placeholder_doi"][0]["value"] == "10.1001/jamanetworkopen.2024.xxxx"

    def test_detects_placeholder_doi_uppercase_normalized(self):
        # normalize_doi lowercases, so XXXX → xxxx before detect_issues is called
        # But detect_issues receives already-normalized dois; test that lowercase works
        issues = detect_issues(["10.1001/jamanetworkopen.2024.xxxx"], [], "Q039")
        assert len(issues["placeholder_doi"]) == 1

    def test_detects_future_prefix_doi(self):
        issues = detect_issues(["10.1007/s40279-026-02401-y"], [], "Q027")
        assert len(issues["future_prefix_doi"]) == 1

    def test_detects_typo_doi(self):
        # 0.1123/... → 10.1123/...
        raw_lines = ["3. 0.1123/ijsnem.2013-0054"]
        issues = detect_issues([], raw_lines, "Q037")
        assert len(issues["typo_doi_autofixed"]) == 1
        autofixed = issues["typo_doi_autofixed"][0]
        assert autofixed["original"] == "0.1123/ijsnem.2013-0054"
        assert autofixed["fixed"] == "10.1123/ijsnem.2013-0054"

    def test_no_false_positives(self):
        issues = detect_issues(["10.1080/02640414.2016.1210197"], [], "Q001")
        assert issues["placeholder_doi"] == []
        assert issues["future_prefix_doi"] == []
        assert issues["typo_doi_autofixed"] == []
