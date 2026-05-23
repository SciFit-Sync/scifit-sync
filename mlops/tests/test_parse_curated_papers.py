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
