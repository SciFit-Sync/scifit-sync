"""스포츠 과학 논문 크롤러 (OpenAlex 메인 + PubMed 보조 + cascading fulltext).

Task 10에서 단일 PubMed 소스 의존을 OpenAlex 메인 검색으로 전환하고, PubMed는
publication_types 메타 보강 + PMID 식별자 확보용 보조 소스로 격하했다.
본문은 PMC → Europe PMC cascading으로 회수율을 끌어올린다.

흐름:
  카테고리별 OpenAlex 검색 + PubMed 보조 검색 → DOI 기반 merge →
  round-robin dedup → cascading fulltext → evidence_weight 산출.

Rate limit: NCBI는 API 키 없으면 3 req/s, 있으면 10 req/s. OpenAlex는 polite pool.
"""

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict

import requests
from mlops.pipeline.config import (
    EUROPEPMC_BASE_URL,
    EUROPEPMC_RATE_LIMIT,
    MAX_PAPERS_PER_RUN,
    NCBI_API_KEY,
    NCBI_BASE_URL,
    NCBI_HTTP_MAX_BACKOFF,
    NCBI_HTTP_MAX_RETRIES,
    NCBI_HTTP_TIMEOUT,
    NCBI_RATE_LIMIT,
    OPENALEX_BASE_URL,
    OPENALEX_CIRCUIT_BREAKER_THRESHOLD,
    OPENALEX_MAILTO,
    OPENALEX_MAX_PER_CATEGORY,
    OPENALEX_MAX_RETRIES,
    OPENALEX_RATE_LIMIT,
    PMC_FULLTEXT_MAX_ATTEMPTS,
    PMC_FULLTEXT_RETRY_BACKOFF_BASE,
    PMC_FULLTEXT_RETRY_BACKOFF_MAX,
    PUBMED_MAX_PER_CATEGORY,
    STRICT_PUBLICATION_FILTER,
)
from mlops.pipeline.europepmc import EuropePMCClient
from mlops.pipeline.evidence import calculate_evidence_weight
from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection
from mlops.pipeline.oa_fetcher import PaperRef, build_default_chain, fetch_chain
from mlops.pipeline.openalex import OpenAlexClient
from mlops.pipeline.pmc import PMCClient

logger = logging.getLogger(__name__)

# 추천 시스템 근거 데이터를 다양한 축으로 수집하기 위한 카테고리별 쿼리.
# 단일 광범위 쿼리는 NCBI relevance 정렬이 메타분석 한두 편에 편중되기 쉬워,
# 추천 알고리즘이 필요로 하는 세부 결정 축(볼륨/강도/빈도 등)이 비균등하게 수집된다.
#
# 각 쿼리는 PubMed에서 실제 hit count를 측정해 효용성을 검증했다
# (`mlops/scripts/verify_queries.py` 참조). filter_level에 따라 publication-type
# 필터가 단계적으로 완화된다:
#   - "strict": RCT/메타분석/시스템 리뷰 + free full text. 메타분석이 풍부한 주류 주제.
#   - "semi":   RCT/메타분석/시스템 리뷰만 (free full text 제외). abstract로도 RAG에
#               충분한 좁은 임상 주제 (failure_rir, periodization, 부위별 등).
#   - "loose":  publication type 필터 없음 (humans/adults만). 메커니즘 이론·신규 분야·
#               추천 시스템·프로그램 설계처럼 RCT가 거의 없는 영역.
SEARCH_QUERY_CATEGORIES: list[tuple[str, str, str]] = [
    # ── strict (RCT/메타/SR + free full text) ──
    (
        "volume",
        '("resistance training") AND '
        '("training volume" OR "volume load" OR "sets per muscle group" OR "weekly sets") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "intensity",
        '("resistance training") AND '
        '("training intensity" OR "%1RM" OR "high load" OR "low load") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "frequency",
        '("resistance training") AND '
        '("training frequency" OR "weekly frequency" OR "sessions per week") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "hypertrophy_strength",
        '("resistance training" OR "strength training") AND '
        '("muscle hypertrophy" OR "muscle thickness" OR "cross-sectional area" '
        'OR "muscle strength" OR "maximal strength" OR "1RM") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "trained_status",
        '("resistance training") AND '
        '("trained individuals" OR "resistance-trained" OR "experienced lifters" '
        'OR "untrained individuals" OR "beginners" OR "novice") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "rest_interval",
        '("resistance training") AND '
        '("rest interval" OR "rest period" OR "inter-set rest" OR "between-set rest" '
        'OR "recovery between sets" OR "inter-set recovery") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "performance") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "machine_vs_freeweight",
        '("resistance training") AND '
        '("machine" OR "free weight" OR "exercise machine" OR "selectorized" OR "plate loaded") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "biomechanics" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "emg_activation",
        '("resistance training" OR "strength training") AND '
        '("electromyography" OR "EMG" OR "muscle activation" OR "neural drive") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "doms_recovery",
        '("resistance training") AND '
        '("delayed onset muscle soreness" OR "DOMS" OR "muscle damage" OR "exercise-induced muscle damage") AND '
        '("recovery" OR "muscle hypertrophy" OR "performance") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "injury_prevention",
        '("resistance training") AND '
        '("injury prevention" OR "lower back pain" OR "shoulder impingement" '
        'OR "rotator cuff" OR "knee injury" OR "musculoskeletal injury") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "range_of_motion",
        '("resistance training") AND '
        '("range of motion" OR "ROM" OR "full range" OR "partial range" OR "lengthened position") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "contraction_mode",
        '("resistance training") AND '
        '("eccentric" OR "concentric" OR "isometric" OR "contraction mode") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "chest_training",
        '("resistance training") AND '
        '("bench press" OR "pectoral" OR "chest" OR "pectoralis major") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "legs_training",
        '("resistance training") AND '
        '("squat" OR "deadlift" OR "leg press" OR "quadriceps" OR "hamstring" OR "gluteus") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "arms_training",
        '("resistance training") AND '
        '("biceps curl" OR "triceps extension" OR "elbow flexion" OR "elbow extension" OR "arm exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "load_progression",
        '("resistance training") AND '
        '("progressive overload" OR "load progression" OR "training progression" '
        'OR "incremental loading" OR "weight progression" OR "progressive resistance") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "athletic performance") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "muscular_endurance",
        '("resistance training") AND '
        '("muscular endurance" OR "local muscular endurance" OR "muscle endurance") AND '
        '("muscle strength" OR "performance" OR "fatigue resistance") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "concurrent_training",
        '("resistance training") AND '
        '("concurrent training" OR "aerobic training" OR "interference effect" OR "combined training") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "warm_up_cool_down",
        '("resistance training" OR "strength training" OR "exercise performance") AND '
        '("warm-up" OR "warm up" OR "specific warm-up" OR "general warm-up" '
        'OR "dynamic stretching" OR "post-activation potentiation" '
        'OR "cool-down" OR "cool down" OR "preparatory exercise") AND '
        '("muscle strength" OR "performance" OR "injury prevention" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "exercise_variation",
        '("resistance training") AND '
        '("exercise variation" OR "variation" OR "different exercises" OR "exercise diversity") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "instability_training",
        '("resistance training" OR "strength training") AND '
        '("instability training" OR "unstable surface" OR "unstable training" '
        'OR "balance training" OR "stability ball" OR "Swiss ball" OR "BOSU" '
        'OR "wobble board") AND '
        '("muscle strength" OR "muscle activation" OR "core stability" OR "balance") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "detraining",
        '("resistance training") AND '
        '("detraining" OR "training cessation" OR "muscle atrophy" OR "strength loss") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "protein_nutrition",
        '("resistance training") AND '
        '("protein intake" OR "protein supplementation" OR "amino acids" OR "dietary protein") AND '
        '("muscle hypertrophy" OR "muscle protein synthesis" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "sleep_recovery",
        '("resistance training" OR "strength training") AND '
        '("sleep" OR "sleep deprivation" OR "sleep quality") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "recovery" OR "performance") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "unilateral_training",
        '("resistance training") AND '
        '("unilateral training" OR "single-leg" OR "single-arm" OR "bilateral deficit") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "functional_training",
        '("functional training" OR "functional resistance training" OR "movement-based training" '
        'OR "multi-planar exercise") AND '
        '("muscle strength" OR "physical function" OR "balance" OR "athletic performance") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "obesity_weight_loss",
        '("resistance training" OR "strength training") AND '
        '("obesity" OR "overweight" OR "weight loss" OR "fat mass reduction") AND '
        '("body composition" OR "muscle mass" OR "fat loss" OR "energy expenditure") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "rpe_perceived_exertion",
        '("rating of perceived exertion" OR "RPE" OR "perceived exertion" OR "session RPE") AND '
        '("resistance training" OR "training load" OR "muscle strength" OR "intensity prescription") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    (
        "exercise_adherence",
        '("resistance training" OR "strength training" OR "exercise program") AND '
        '("exercise adherence" OR "training compliance" OR "dropout" OR "behavior change") AND '
        '("humans" OR "adults")',
        "strict",
    ),
    # ── semi (RCT/메타/SR만, free full text 제외) ──
    (
        "failure_rir",
        '("resistance training") AND '
        '("training to failure" OR "muscular failure" OR "momentary failure" '
        'OR "task failure" OR "volitional failure" OR "repetitions in reserve" '
        'OR "RIR" OR "proximity to failure") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "periodization",
        '("resistance training" OR "strength training") AND '
        '("periodization" OR "periodized training" OR "linear periodization" '
        'OR "undulating periodization" OR "daily undulating" OR "block periodization" '
        'OR "non-linear periodization") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "athletic performance") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "tempo_tut",
        '("resistance training") AND '
        '("tempo" OR "repetition duration" OR "movement tempo" OR "lifting tempo" '
        'OR "time under tension" OR "lifting velocity" OR "concentric tempo" '
        'OR "eccentric tempo" OR "movement velocity" OR "repetition cadence") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "compound_isolation",
        '("resistance training") AND '
        '("compound exercise" OR "multi-joint exercise" OR "multi joint" '
        'OR "single-joint exercise" OR "single joint" OR "isolation exercise" '
        'OR "isolated exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "back_training",
        '("resistance training" OR "strength training") AND '
        '("lat pulldown" OR "seated row" OR "barbell row" OR "pull-up" OR "chin-up" '
        'OR "back exercise" OR "latissimus dorsi" OR "back muscle" OR "posterior chain") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "shoulders_training",
        '("resistance training" OR "strength training") AND '
        '("shoulder training" OR "shoulder press" OR "overhead press" OR "military press" '
        'OR "deltoid" OR "lateral raise" OR "front raise" OR "rear delt" '
        'OR "rotator cuff" OR "shoulder exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "core_training",
        '("resistance training" OR "core training" OR "trunk training") AND '
        '("abdominal exercise" OR "core exercise" OR "trunk exercise" '
        'OR "trunk stability" OR "core stability" OR "plank" '
        'OR "rectus abdominis" OR "transverse abdominis" OR "lumbar stabilization") AND '
        '("muscle activation" OR "muscle strength" OR "muscle hypertrophy" OR "trunk strength") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "minimum_effective_dose",
        '("resistance training") AND '
        '("minimum effective dose" OR "minimal dose" OR "low volume training" '
        'OR "abbreviated training" OR "single set" OR "time-efficient training" '
        'OR "low frequency training") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "stretching_flexibility",
        '("resistance training" OR "strength training" OR "exercise performance") AND '
        '("static stretching" OR "dynamic stretching" OR "PNF stretching" '
        'OR "flexibility training" OR "stretching protocol") AND '
        '("muscle strength" OR "range of motion" OR "athletic performance" OR "muscle hypertrophy") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "cross_education",
        '("resistance training" OR "unilateral training" OR "strength training") AND '
        '("cross education" OR "cross-education" OR "contralateral effect" '
        'OR "unilateral strength transfer") AND '
        '("muscle strength" OR "neural adaptation") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "muscle_fiber_type",
        '("resistance training" OR "strength training") AND '
        '("muscle fiber type" OR "fiber type composition" OR "type I fibers" OR "type II fibers" '
        'OR "slow twitch" OR "fast twitch" OR "myosin heavy chain") AND '
        '("muscle hypertrophy" OR "muscle adaptation" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    (
        "neuromuscular_adaptation",
        '("resistance training" OR "strength training") AND '
        '("neuromuscular adaptation" OR "neural adaptation" OR "motor unit recruitment" '
        'OR "firing rate" OR "motor unit") AND '
        '("muscle strength" OR "force production" OR "neural drive") AND '
        '("humans" OR "adults")',
        "semi",
    ),
    # ── loose (publication type 필터 없음) ──
    (
        "personalized_prescription",
        '("personalized exercise prescription" OR "individualized exercise program") AND '
        '("resistance training" OR "strength training") AND '
        '("humans" OR "adults")',
        "loose",
    ),
    (
        "deload_recovery",
        '("resistance training" OR "strength training") AND '
        '("deload" OR "recovery week" OR "training taper" OR "tapering" '
        'OR "active rest" OR "training cycle" OR "rest week" OR "recovery period") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "fatigue" OR "performance") AND '
        '("humans" OR "adults")',
        "loose",
    ),
    (
        "exercise_order",
        '("resistance training" OR "strength training") AND '
        '("exercise order" OR "exercise sequence" OR "exercise sequencing" '
        'OR "training order" OR "agonist-antagonist") AND '
        '("muscle strength" OR "muscle hypertrophy" OR "performance" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "loose",
    ),
    (
        "training_split",
        '("resistance training" OR "strength training") AND '
        '("training split" OR "split routine" OR "push pull legs" OR "upper lower split" '
        'OR "full body training" OR "split training" OR "training program design") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "loose",
    ),
    (
        "advanced_techniques",
        '("resistance training" OR "strength training") AND '
        '("drop set" OR "drop-set" OR "superset" OR "rest-pause" OR "rest pause" '
        'OR "cluster set" OR "pre-exhaustion" OR "post-exhaustion") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        "loose",
    ),
    (
        "bodyweight_training",
        '("bodyweight exercise" OR "body weight exercise" OR "bodyweight training" '
        'OR "body weight training" OR "calisthenics" OR "self-loading exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation" OR "physical fitness") AND '
        '("humans" OR "adults")',
        "loose",
    ),
    (
        "mechanical_tension",
        '("resistance training" OR "strength training") AND '
        '("mechanical tension" OR "metabolic stress" OR "muscle damage" '
        'OR "hypertrophy mechanism" OR "muscle protein synthesis") AND '
        '("muscle hypertrophy" OR "muscle growth") AND '
        '("humans" OR "adults")',
        "loose",
    ),
    (
        "individual_response",
        '("resistance training" OR "strength training") AND '
        '("individual response" OR "responders" OR "non-responders" '
        'OR "inter-individual variability" OR "training response variability" '
        'OR "genetic factors") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        "loose",
    ),
    (
        "circadian_time_of_day",
        '("resistance training" OR "strength training" OR "exercise training") AND '
        '("time of day" OR "circadian rhythm" OR "morning training" OR "evening training" '
        'OR "diurnal variation") AND '
        '("muscle strength" OR "exercise performance" OR "muscle hypertrophy") AND '
        '("humans" OR "adults")',
        "loose",
    ),
]

# Task 10: publication-type 필터는 환경변수 토글로 단일화.
# STRICT_PUBLICATION_FILTER=true면 PubMed 보조 검색에 strict RCT/메타/SR + free full text 필터를 붙인다.
# 기본은 False — 65개 카테고리 baseline에서 회수율을 위해 필터를 완전히 끄는 정책.
# OpenAlex 메인 검색으로 메타분석을 충분히 확보하므로 PubMed strict 필터의 의미가 약해졌다.
_STRICT_PUB_FILTER = (
    ' AND ("randomized controlled trial"[Publication Type] '
    'OR "meta-analysis"[Publication Type] '
    'OR "systematic review"[Publication Type]) '
    'AND "free full text"[Filter]'
)

# 기존 심볼 deprecated alias (refresh_search_categories.py / verify_queries.py 호환).
# Task 11 이후 호출부 정리 시 함께 제거 예정.
COMMON_PUBLICATION_FILTER = _STRICT_PUB_FILTER
SEMI_STRICT_PUBLICATION_FILTER = (
    ' AND ("randomized controlled trial"[Publication Type] '
    'OR "meta-analysis"[Publication Type] '
    'OR "systematic review"[Publication Type])'
)


def get_publication_filter() -> str:
    """STRICT_PUBLICATION_FILTER가 True일 때만 PubMed strict 필터를 반환.

    환경변수 토글 기반 — 모듈 import 시점에 캡처된 config 값이 아니라 현재 모듈의
    전역을 본다(테스트에서 `patch.object(crawler_mod, "STRICT_PUBLICATION_FILTER", ...)`로
    덮어쓸 수 있도록).
    """
    return _STRICT_PUB_FILTER if STRICT_PUBLICATION_FILTER else ""


def filter_for_level(filter_level: str) -> str:
    """filter_level 문자열을 PubMed term 접미 필터로 변환 (deprecated).

    Task 10 이후 publication-type 필터는 STRICT_PUBLICATION_FILTER 토글로 통일됐다.
    이 함수는 `refresh_search_categories.py` 등 기존 스크립트 호환을 위해 유지하며,
    Task 11 이후 일괄 제거 예정.
    """
    if filter_level == "strict":
        return _STRICT_PUB_FILTER
    if filter_level == "semi":
        return SEMI_STRICT_PUBLICATION_FILTER
    if filter_level == "loose":
        return ""
    raise ValueError(f"알 수 없는 filter_level: {filter_level!r} (strict|semi|loose 중 하나여야 함)")


_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def _request_with_rate_limit(
    url: str,
    params: dict,
    max_retries: int = NCBI_HTTP_MAX_RETRIES,
    max_backoff: float = NCBI_HTTP_MAX_BACKOFF,
) -> requests.Response:
    """Rate limit 준수 + transient 에러에 대해 지수 백오프 재시도.

    Retry 대상:
      - ChunkedEncodingError: NCBI eutils가 HTTP body 도중 끊김 (WSL→NCBI 환경에서 실측 빈번)
      - ConnectionError: 일시적 connection refused/reset
      - Timeout: read timeout
      - HTTPError 429: rate limit 초과
      - HTTPError 5xx: 서버 장애 (transient)

    Retry 비대상:
      - HTTPError 4xx (404 등): 영구 에러 — 재시도 의미 없음
      - HTTP 200 + 깨진 body (JSON/XML 파싱 실패): 호출부에서 처리
    """
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        if attempt == 0:
            time.sleep(NCBI_RATE_LIMIT)
        else:
            backoff = min(max_backoff, NCBI_RATE_LIMIT * (2**attempt))
            logger.warning("NCBI 요청 재시도 %d/%d (%.1fs 백오프): %s", attempt + 1, max_retries, backoff, last_exc)
            time.sleep(backoff)

        try:
            resp = requests.get(url, params=params, timeout=NCBI_HTTP_TIMEOUT)
            resp.raise_for_status()
            _ = resp.content  # body 강제 fetch — chunked 응답 중간 끊김도 여기서 raise
            return resp
        except _RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            continue
        except requests.exceptions.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status is not None and (status == 429 or 500 <= status < 600):
                last_exc = e
                continue
            raise

    assert last_exc is not None
    raise last_exc


def _fulltext_retry_backoff(attempt: int) -> float:
    """fulltext 함수 레벨 재시도 backoff 계산."""
    return min(PMC_FULLTEXT_RETRY_BACKOFF_MAX, PMC_FULLTEXT_RETRY_BACKOFF_BASE * (2**attempt))


def search_pmids(
    query: str,
    max_results: int = PUBMED_MAX_PER_CATEGORY,
    min_date: str | None = None,
    max_date: str | None = None,
) -> list[str]:
    """PubMed에서 쿼리 조건에 맞는 PMID 목록을 검색한다.

    Args:
        query: PubMed 검색 쿼리
        max_results: 최대 결과 수
        min_date: 최소 날짜 (YYYY/MM/DD)
        max_date: 최대 날짜 (YYYY/MM/DD)

    Returns:
        PMID 문자열 리스트
    """
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }
    if min_date:
        params["mindate"] = min_date
        params["datetype"] = "pdat"
    if max_date:
        params["maxdate"] = max_date

    logger.info("PubMed 검색: max_results=%d, min_date=%s", max_results, min_date)
    resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/esearch.fcgi", params)
    data = resp.json()

    pmids = data.get("esearchresult", {}).get("idlist", [])
    logger.info("검색 결과: %d건 (총 %s건 중)", len(pmids), data.get("esearchresult", {}).get("count", "?"))
    return pmids


def fetch_paper_metadata(pmids: list[str]) -> list[PaperMeta]:
    """PMID 목록으로 논문 메타데이터를 일괄 조회한다.

    Args:
        pmids: PMID 문자열 리스트 (최대 200개씩 배치)

    Returns:
        PaperMeta 리스트
    """
    results: list[PaperMeta] = []
    batch_size = 200

    for i in range(0, len(pmids), batch_size):
        batch = pmids[i : i + batch_size]
        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "xml",
            "rettype": "abstract",
        }

        resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/efetch.fcgi", params)
        root = ET.fromstring(resp.content)

        for article in root.findall(".//PubmedArticle"):
            meta = _parse_pubmed_article(article)
            if meta:
                results.append(meta)

        logger.info("메타데이터 수집: %d/%d", len(results), len(pmids))

    return results


def _parse_pubmed_article(article: ET.Element) -> PaperMeta | None:
    """PubmedArticle XML 요소에서 메타데이터를 추출한다."""
    try:
        medline = article.find(".//MedlineCitation")
        if medline is None:
            return None

        pmid_el = medline.find("PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        article_el = medline.find("Article")
        if article_el is None:
            return None

        # 제목
        title_el = article_el.find("ArticleTitle")
        title = _get_text(title_el)

        # 저자
        authors = []
        for author in article_el.findall(".//Author"):
            last = author.findtext("LastName", "")
            first = author.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {first}".strip())
        authors_str = ", ".join(authors[:10])  # 최대 10명
        if len(authors) > 10:
            authors_str += " et al."

        # 저널
        journal_el = article_el.find(".//Journal/Title")
        journal = journal_el.text if journal_el is not None else ""

        # 출판 연도
        year_el = article_el.find(".//Journal/JournalIssue/PubDate/Year")
        year = int(year_el.text) if year_el is not None and year_el.text else None

        # DOI
        doi = ""
        for eid in article.findall(".//ArticleIdList/ArticleId"):
            if eid.get("IdType") == "doi":
                doi = eid.text or ""
                break

        # 초록
        abstract_parts = []
        for abs_text in article_el.findall(".//Abstract/AbstractText"):
            label = abs_text.get("Label", "")
            text = _get_text(abs_text)
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        # 출판 타입 (PublicationTypeList)
        publication_types = [
            (pt.text or "").strip() for pt in article.findall(".//PublicationTypeList/PublicationType") if pt.text
        ]

        return PaperMeta(
            pmid=pmid,
            title=title,
            authors=authors_str,
            journal=journal,
            published_year=year,
            doi=doi,
            abstract=abstract,
            publication_types=publication_types,
        )
    except Exception:
        logger.warning("논문 파싱 실패: %s", ET.tostring(article, encoding="unicode")[:200])
        return None


def _get_text(el: ET.Element | None) -> str:
    """XML 요소의 전체 텍스트를 추출 (하위 태그 포함)."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


# NCBI elink/efetch가 ERROR 응답 등에서 JSON 문자열 값 안에 escape 안 된
# raw C0 control character(예: literal `\n`)를 넣어 RFC 8259 위반 응답을 반환하는
# 결정론적 server-side 버그가 있다. 같은 PMID는 항상 같은 깨진 응답을 주므로
# retry는 무의미하다. sanitize 후 한 번 더 파싱해 ``linksets`` / ``ERROR`` 필드를
# 보존한다 (제어 문자는 보조 정보이므로 공백 치환해도 PMC 링크 추출에 영향 없음).
_NCBI_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f]")


def _parse_ncbi_json(raw: str) -> dict | None:
    """NCBI JSON 응답을 파싱. malformed 응답(raw control char 포함)은 sanitize 후 재시도.

    Returns:
        파싱된 dict, 또는 sanitize 후에도 파싱 불가능하면 None.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        try:
            return json.loads(_NCBI_CONTROL_CHARS_RE.sub(" ", raw))
        except json.JSONDecodeError:
            return None


def _resolve_pmc_id(pmid: str, max_attempts: int = PMC_FULLTEXT_MAX_ATTEMPTS) -> str | None:
    """PMID → PMCID 변환.

    NCBI elink는 가끔 ERROR 필드에 raw control character가 포함된 malformed JSON을
    반환한다. 실측 데이터(2026-05-20, 20 PMID × 3회 호출):
      - 정상 응답: 37%
      - HTTP timeout: 38% (대부분 `_request_with_rate_limit` 내부 retry로 복구)
      - ERROR 응답(server-side TXCLIENT exception): 25%
      - sanitize 후 파싱 실패: 0% (sanitize가 모든 케이스를 cover)

    EuropePMC fallback은 PMID-PMC OA mirror에 없는 논문(실측 5/5 NOT_AVAILABLE)을
    못 잡아주므로 ERROR 응답을 즉시 포기하면 본문 회수율이 손실된다. ERROR는
    33%가 transient(다음 호출에서 정상 응답)이므로 1회만 재시도한다.

    Retry 전략:
      - JSON 파싱 실패: sanitize 후 한 번만 재시도, 그래도 실패하면 None (server-side 결정론적)
      - ERROR 필드 응답: 1회만 재시도 (transient 33% 회복)
      - HTTP 에러: max_attempts 한도까지 재시도

    Returns:
        PMCID 문자열, 또는 PMC 버전이 없거나 JSON malformed이면 None.

    Raises:
        RuntimeError: 모든 HTTP retry가 실패했을 때 (마지막 예외를 cause로 포함).
    """
    last_exc: Exception | None = None
    error_retried = False  # ERROR 응답은 1회만 재시도
    for attempt in range(max_attempts):
        if attempt > 0:
            wait = _fulltext_retry_backoff(attempt - 1)
            # ERROR transient 재시도는 1회 한정. HTTP retry는 max_attempts 한도.
            # 두 경우의 한도가 다르므로 로그 메시지도 구분한다.
            is_error_retry = isinstance(last_exc, RuntimeError) and str(last_exc).startswith("NCBI ERROR")
            if is_error_retry:
                logger.info(
                    "PMC elink ERROR transient 재시도 (1회 한정, %.1fs 대기): PMID=%s last_err=%s",
                    wait,
                    pmid,
                    last_exc,
                )
            else:
                logger.info(
                    "PMC elink HTTP 재시도 %d/%d (%.1fs 대기): PMID=%s last_err=%s",
                    attempt + 1,
                    max_attempts,
                    wait,
                    pmid,
                    last_exc,
                )
            time.sleep(wait)

        try:
            params = {
                "dbfrom": "pubmed",
                "db": "pmc",
                "id": pmid,
                "retmode": "json",
            }
            resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/elink.fcgi", params)
        except requests.exceptions.RequestException as e:
            last_exc = e
            logger.warning(
                "PMC elink HTTP 최종 실패 (시도 %d/%d): PMID=%s err=%s",
                attempt + 1,
                max_attempts,
                pmid,
                e,
            )
            continue

        data = _parse_ncbi_json(resp.text)
        if data is None:
            # sanitize 후에도 파싱 실패 → server-side malformed (결정론적). retry 무의미.
            logger.warning(
                "PMC elink 응답 파싱 실패 (sanitize 후에도) → PMC 미존재로 처리: PMID=%s",
                pmid,
            )
            return None

        for linkset in data.get("linksets", []):
            for linksetdb in linkset.get("linksetdbs", []):
                if linksetdb.get("dbto") == "pmc":
                    links = linksetdb.get("links", [])
                    if links:
                        return str(links[0])

        # linksets 비어 있고 ERROR 필드가 있으면 transient 가능성(33%) → 1회만 재시도
        if data.get("ERROR") and not error_retried:
            error_retried = True
            error_msg = str(data["ERROR"])[:80]
            last_exc = RuntimeError(f"NCBI ERROR: {error_msg}")
            logger.info(
                "PMC elink ERROR 응답 → 1회 재시도: PMID=%s err=%s",
                pmid,
                error_msg,
            )
            continue
        # 응답 정상 + PMC 링크 없음 (또는 ERROR retry 후에도 동일) — 진짜 미존재.
        return None

    raise RuntimeError(f"PMC elink 재시도 한도 초과: PMID={pmid}") from last_exc


def _fetch_pmc_sections(pmid: str, pmc_id: str, max_attempts: int = PMC_FULLTEXT_MAX_ATTEMPTS) -> list[PaperSection]:
    """PMCID로 PMC efetch XML을 받아 섹션 파싱. XML 파싱 실패는 재시도.

    Raises:
        RuntimeError: 모든 재시도가 실패했을 때 (마지막 예외를 cause로 포함).
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        if attempt > 0:
            wait = _fulltext_retry_backoff(attempt - 1)
            logger.info(
                "PMC efetch 재시도 %d/%d (%.1fs 대기): PMID=%s PMC=%s last_err=%s",
                attempt + 1,
                max_attempts,
                wait,
                pmid,
                pmc_id,
                last_exc,
            )
            time.sleep(wait)

        try:
            params = {
                "db": "pmc",
                "id": pmc_id,
                "retmode": "xml",
            }
            resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/efetch.fcgi", params)
            root = ET.fromstring(resp.content)
            return _parse_pmc_sections(root)
        except ET.ParseError as e:
            last_exc = e
            logger.warning(
                "PMC XML 파싱 실패 (시도 %d/%d): PMID=%s PMC=%s err=%s",
                attempt + 1,
                max_attempts,
                pmid,
                pmc_id,
                e,
            )
            continue
        except requests.exceptions.RequestException as e:
            last_exc = e
            logger.warning(
                "PMC efetch HTTP 최종 실패 (시도 %d/%d): PMID=%s PMC=%s err=%s",
                attempt + 1,
                max_attempts,
                pmid,
                pmc_id,
                e,
            )
            continue

    raise RuntimeError(f"PMC efetch 재시도 한도 초과: PMID={pmid} PMC={pmc_id}") from last_exc


def fetch_pmc_fulltext(pmid: str) -> list[PaperSection]:
    """PMC에서 전문 XML을 가져와 섹션별로 파싱한다.

    fulltext 회수율을 최대화하기 위한 두 단계 재시도 구조:
      1. HTTP layer (`_request_with_rate_limit`): transient 네트워크/서버 에러 재시도
      2. 함수 layer (`_resolve_pmc_id` / `_fetch_pmc_sections`): HTTP 200인데 body가
         깨져 JSON/XML 파싱이 실패하는 케이스 재시도

    모든 retry 파라미터는 config.py를 통해 환경변수로 조정 가능
    (NCBI_HTTP_MAX_RETRIES, NCBI_HTTP_MAX_BACKOFF, NCBI_HTTP_TIMEOUT,
    PMC_FULLTEXT_MAX_ATTEMPTS, PMC_FULLTEXT_RETRY_BACKOFF_BASE/_MAX).

    Args:
        pmid: PubMed ID

    Returns:
        PaperSection 리스트 (PMC 버전이 없으면 빈 리스트). HTTP 또는 파싱이 모든 재시도
        끝에 실패하면 RuntimeError를 raise한다. Task 8 이후 abstract fallback은 제거됐고,
        본문 없는 paper는 cascading의 다음 소스로 넘어가거나 폐기된다.
    """
    pmc_id = _resolve_pmc_id(pmid)
    if pmc_id is None:
        logger.debug("PMC 전문 없음: PMID=%s", pmid)
        return []
    return _fetch_pmc_sections(pmid, pmc_id)


def _parse_pmc_sections(root: ET.Element) -> list[PaperSection]:
    """PMC XML에서 본문 섹션을 추출한다."""
    sections: list[PaperSection] = []

    body = root.find(".//body")
    if body is None:
        return sections

    for sec in body.findall(".//sec"):
        title_el = sec.find("title")
        section_name = title_el.text.strip() if title_el is not None and title_el.text else "Untitled"

        paragraphs = []
        for p in sec.findall("p"):
            text = _get_text(p)
            if text:
                paragraphs.append(text)

        content = "\n".join(paragraphs)
        if content.strip():
            sections.append(PaperSection(name=section_name, content=content))

    return sections


def _round_robin_dedup(
    per_category: list[tuple[str, list[str]]],
    existing: set[str],
    max_total: int,
) -> tuple[list[str], dict[str, set[str]]]:
    """카테고리별 PMID 리스트를 round-robin으로 dedup하며 cap까지 누적한다.

    각 round에서 카테고리를 한 바퀴 돌며 그 round 위치의 PMID를 하나씩 가져온다.
    단순 FIFO cap(앞쪽 카테고리가 cap을 모두 채우는 방식)이 카테고리 다양성을
    무너뜨리는 문제를 해결한다.

    동작 규칙:
      - 동일 PMID가 여러 카테고리에 매칭되면 카테고리 메타를 합집합으로 누적한다.
      - cap 도달 후에도 기존 PMID에 대한 카테고리 메타 추가는 계속된다 (신규 PMID만 거부).
      - existing 집합의 PMID는 어떤 경우에도 제외한다.

    Args:
        per_category: (카테고리명, 해당 카테고리에서 검색된 PMID 리스트) 튜플들.
        existing: 이미 수집된 PMID 집합 (중복 방지).
        max_total: 신규 PMID 누적 상한.

    Returns:
        (PMID 추가 순서 리스트, PMID → 카테고리명 set 매핑) 튜플.
    """
    pmid_to_categories: dict[str, set[str]] = defaultdict(set)
    pmid_order: list[str] = []

    max_len = max((len(pmids) for _, pmids in per_category), default=0)
    for i in range(max_len):
        for name, pmids in per_category:
            if i >= len(pmids):
                continue
            pmid = pmids[i]
            if pmid in existing:
                continue
            if pmid in pmid_to_categories:
                pmid_to_categories[pmid].add(name)
                continue
            if len(pmid_to_categories) >= max_total:
                continue
            pmid_order.append(pmid)
            pmid_to_categories[pmid].add(name)

    return pmid_order, dict(pmid_to_categories)


# ─────────────────────────────────────────────────────────────────────────────
# Task 10: OpenAlex 통합 + DOI 기반 dedup + cascading fulltext
# ─────────────────────────────────────────────────────────────────────────────

# CATEGORY_OPENALEX_MAPPING: SEARCH_QUERY_CATEGORIES 65개 카테고리에 대응되는
# OpenAlex 검색 파라미터 (concept_ids + keywords).
#
# OpenAlex 2024 schema 변경으로 concepts deprecated → topics 사용.
# Phase 1은 keyword search만으로 동작 (concept_ids=[]).
# Topics 마이그레이션은 후속 D-issue로 분리 (T-prefix ID 매핑 필요).
#
# keywords는 OpenAlex `search` 파라미터에 join되어 텍스트 검색으로 사용된다.
CATEGORY_OPENALEX_MAPPING: dict[str, dict] = {
    "volume": {"concept_ids": [], "keywords": ["training volume", "volume load", "weekly sets", "sets per muscle"]},
    "intensity": {"concept_ids": [], "keywords": ["training intensity", "%1RM", "high load", "low load"]},
    "frequency": {"concept_ids": [], "keywords": ["training frequency", "weekly frequency", "sessions per week"]},
    "hypertrophy_strength": {"concept_ids": [], "keywords": ["muscle hypertrophy", "muscle strength", "1RM"]},
    "trained_status": {"concept_ids": [], "keywords": ["trained individuals", "untrained", "novice", "beginners"]},
    "rest_interval": {"concept_ids": [], "keywords": ["rest interval", "inter-set rest"]},
    "failure_rir": {"concept_ids": [], "keywords": ["training to failure", "repetitions in reserve", "RIR"]},
    "exercise_order": {"concept_ids": [], "keywords": ["exercise order", "exercise sequence"]},
    "recommendation_system": {
        "concept_ids": [],
        "keywords": ["exercise recommendation system", "fitness recommendation", "workout recommendation"],
    },
    "personalized_prescription": {
        "concept_ids": [],
        "keywords": ["personalized exercise prescription", "individualized exercise program"],
    },
    "machine_vs_freeweight": {
        "concept_ids": [],
        "keywords": ["machine", "free weight", "selectorized", "plate loaded"],
    },
    "emg_activation": {"concept_ids": [], "keywords": ["electromyography", "EMG", "muscle activation"]},
    "periodization": {"concept_ids": [], "keywords": ["periodization", "linear periodization", "undulating", "block"]},
    "deload_recovery": {"concept_ids": [], "keywords": ["deload", "recovery week", "tapering"]},
    "doms_recovery": {"concept_ids": [], "keywords": ["delayed onset muscle soreness", "DOMS", "muscle damage"]},
    "older_adults": {"concept_ids": [], "keywords": ["older adults", "elderly", "sarcopenia", "aging"]},
    "women_resistance": {"concept_ids": [], "keywords": ["women", "female", "menstrual cycle"]},
    "injury_prevention": {"concept_ids": [], "keywords": ["injury prevention", "lower back pain", "rotator cuff"]},
    "range_of_motion": {"concept_ids": [], "keywords": ["range of motion", "ROM", "full range", "partial range"]},
    "tempo_tut": {
        "concept_ids": [],
        "keywords": ["tempo", "time under tension", "lifting cadence", "movement velocity"],
    },
    "contraction_mode": {"concept_ids": [], "keywords": ["eccentric", "concentric", "isometric"]},
    "compound_isolation": {
        "concept_ids": [],
        "keywords": ["compound exercise", "multi-joint", "single-joint", "isolation exercise"],
    },
    "chest_training": {"concept_ids": [], "keywords": ["bench press", "pectoral", "chest", "pectoralis"]},
    "back_training": {"concept_ids": [], "keywords": ["row", "pull-down", "latissimus", "pull-up"]},
    "legs_training": {"concept_ids": [], "keywords": ["squat", "deadlift", "leg press", "quadriceps", "hamstring"]},
    "shoulders_training": {
        "concept_ids": [],
        "keywords": ["shoulder press", "overhead press", "deltoid", "lateral raise"],
    },
    "arms_training": {"concept_ids": [], "keywords": ["biceps curl", "triceps extension", "elbow flexion"]},
    "core_training": {
        "concept_ids": [],
        "keywords": ["abdominal", "trunk stability", "core stability", "rectus abdominis"],
    },
    "load_progression": {
        "concept_ids": [],
        "keywords": ["progressive overload", "load progression", "training progression"],
    },
    "muscular_endurance": {"concept_ids": [], "keywords": ["muscular endurance", "endurance training"]},
    "concurrent_training": {"concept_ids": [], "keywords": ["concurrent training", "endurance and strength"]},
    "warm_up_cool_down": {"concept_ids": [], "keywords": ["warm-up", "cool-down", "pre-exercise warm up"]},
    "exercise_variation": {"concept_ids": [], "keywords": ["exercise variation", "exercise selection"]},
    "instability_training": {
        "concept_ids": [],
        "keywords": ["instability training", "unstable surface", "balance training"],
    },
    "detraining": {"concept_ids": [], "keywords": ["detraining", "training cessation", "loss of strength"]},
    "protein_nutrition": {"concept_ids": [], "keywords": ["protein intake", "protein supplementation", "amino acid"]},
    "sleep_recovery": {"concept_ids": [], "keywords": ["sleep recovery", "sleep and exercise"]},
    "unilateral_training": {"concept_ids": [], "keywords": ["unilateral training", "single leg", "single arm"]},
    "functional_training": {"concept_ids": [], "keywords": ["functional training", "functional fitness"]},
    "obesity_weight_loss": {"concept_ids": [], "keywords": ["obesity", "weight loss", "fat loss"]},
    "rpe_perceived_exertion": {"concept_ids": [], "keywords": ["rate of perceived exertion", "RPE"]},
    "exercise_adherence": {"concept_ids": [], "keywords": ["exercise adherence", "exercise compliance"]},
    "training_split": {"concept_ids": [], "keywords": ["training split", "push pull legs", "upper lower split"]},
    "advanced_techniques": {"concept_ids": [], "keywords": ["drop set", "supersets", "advanced training techniques"]},
    "bodyweight_training": {"concept_ids": [], "keywords": ["bodyweight training", "calisthenics"]},
    "mechanical_tension": {"concept_ids": [], "keywords": ["mechanical tension", "muscle tension"]},
    "individual_response": {"concept_ids": [], "keywords": ["individual response", "responders", "non-responders"]},
    "circadian_time_of_day": {"concept_ids": [], "keywords": ["time of day", "circadian", "morning vs evening"]},
    "minimum_effective_dose": {"concept_ids": [], "keywords": ["minimum effective dose", "minimal effective volume"]},
    "stretching_flexibility": {"concept_ids": [], "keywords": ["stretching", "flexibility", "static stretching"]},
    "cross_education": {"concept_ids": [], "keywords": ["cross education", "contralateral training effect"]},
    "muscle_fiber_type": {"concept_ids": [], "keywords": ["muscle fiber type", "type I", "type II", "fast twitch"]},
    "neuromuscular_adaptation": {"concept_ids": [], "keywords": ["neuromuscular adaptation", "neural drive"]},
}


def _get_openalex_client() -> OpenAlexClient:
    """OpenAlexClient 인스턴스 생성. 테스트에서 monkeypatch 가능하도록 함수로 분리."""
    return OpenAlexClient(
        base_url=OPENALEX_BASE_URL,
        mailto=OPENALEX_MAILTO,
        rate_limit=OPENALEX_RATE_LIMIT,
        max_retries=OPENALEX_MAX_RETRIES,
        circuit_breaker_threshold=OPENALEX_CIRCUIT_BREAKER_THRESHOLD,
    )


def search_openalex_by_category(category: str, max_results: int) -> list[PaperMeta]:
    """카테고리명을 CATEGORY_OPENALEX_MAPPING으로 변환해 OpenAlex 검색.

    매핑에 없는 카테고리는 카테고리명을 그대로 keyword로 사용한다 (fallback).
    """
    cfg = CATEGORY_OPENALEX_MAPPING.get(
        category,
        {"concept_ids": [], "keywords": [category.replace("_", " ")]},
    )
    client = _get_openalex_client()
    return client.search(
        keywords=cfg["keywords"],
        concept_ids=cfg["concept_ids"],
        max_results=max_results,
    )


def _merge_by_doi(openalex: list[PaperMeta], pubmed: list[PaperMeta]) -> list[PaperMeta]:
    """동일 DOI는 OpenAlex 메타를 우선하고 PubMed로 pmid/publication_types를 보강한다.

    OpenAlex가 abstract/journal 메타가 더 풍부하지만 publication_types와 PMID는
    비어있는 경우가 많아 PubMed 보강이 필요하다.
    """
    by_doi: dict[str, PaperMeta] = {}
    for m in openalex:
        if m.doi:
            by_doi[m.doi] = m
    for m in pubmed:
        if not m.doi:
            continue
        if m.doi in by_doi:
            existing = by_doi[m.doi]
            if not existing.pmid and m.pmid:
                existing.pmid = m.pmid
            if not existing.publication_types and m.publication_types:
                existing.publication_types = m.publication_types
        else:
            by_doi[m.doi] = m
    return list(by_doi.values())


def _round_robin_dedup_metas(
    per_category: list[tuple[str, list[PaperMeta]]],
    existing: set[str],
    max_total: int,
) -> tuple[list[str], dict[str, set[str]], dict[str, PaperMeta]]:
    """PaperMeta 리스트를 round-robin으로 DOI dedup하며 cap까지 누적.

    `_round_robin_dedup`의 DOI 버전. PMID 대신 DOI를 primary key로 사용한다.
    DOI 없는 메타는 자동 폐기 (OpenAlex가 이미 폐기하므로 PubMed-only 경로에서만 발생).

    Returns:
        (DOI 추가 순서, DOI → 카테고리명 set, DOI → PaperMeta) 3-튜플.
    """
    doi_to_meta: dict[str, PaperMeta] = {}
    doi_to_categories: dict[str, set[str]] = defaultdict(set)
    doi_order: list[str] = []

    max_len = max((len(metas) for _, metas in per_category), default=0)
    for i in range(max_len):
        for name, metas in per_category:
            if i >= len(metas):
                continue
            meta = metas[i]
            doi = meta.doi
            if not doi or doi in existing:
                continue
            if doi in doi_to_meta:
                doi_to_categories[doi].add(name)
                continue
            if len(doi_to_meta) >= max_total:
                continue
            doi_to_meta[doi] = meta
            doi_to_categories[doi].add(name)
            doi_order.append(doi)

    return doi_order, dict(doi_to_categories), doi_to_meta


FULLTEXT_PROGRESS_LOG_EVERY = 50


def _attach_fulltext(metas: list[PaperMeta]) -> list[PaperFull]:
    """각 paper에 OA chain (PMC → EuropePMC → OpenAlex PDF → OpenAlex HTML → Unpaywall) 적용.

    fulltext_source가 None으로 남으면 본문 회수 실패 — 호출부가 폐기 결정.

    진행 표시: 매 ``FULLTEXT_PROGRESS_LOG_EVERY`` 편마다 + 마지막 1편에서
    누적 통계를 INFO 로그로 출력. ERROR/retry 로그는 산발적이라 정상 진행을
    체감하기 어렵기 때문에 보조 신호로 사용.
    """
    pmc_client = PMCClient(
        base_url=NCBI_BASE_URL,
        api_key=NCBI_API_KEY,
        rate_limit=NCBI_RATE_LIMIT,
    )
    europepmc_client = EuropePMCClient(
        base_url=EUROPEPMC_BASE_URL,
        rate_limit=EUROPEPMC_RATE_LIMIT,
    )
    chain = build_default_chain(pmc_client, europepmc_client)

    total = len(metas)
    indexed = 0
    sources: dict[str, int] = defaultdict(int)
    started = time.time()

    papers: list[PaperFull] = []
    for i, meta in enumerate(metas, start=1):
        # PMC 시도 전 PMCID 보강. OpenAlex 메타만 `ids.pmcid`를 일부 채우고,
        # PubMed efetch는 pmcid를 추출하지 않는다. pmcid가 비어 있고 PMID가
        # 있으면 elink(PMID→PMCID)로 변환을 시도해 PMC fetch가 가능하도록 한다.
        # 이 fallback이 없으면 PMC 단계를 완전히 스킵하고
        # EuropePMC만 시도해 OA 미보유 paper의 회수율이 0에 가까워진다.
        pmcid = meta.pmcid
        if not pmcid and meta.pmid:
            try:
                resolved = _resolve_pmc_id(meta.pmid)
            except RuntimeError as e:
                logger.debug(
                    "PMC elink 한도 초과 → EuropePMC fallback: PMID=%s err=%s",
                    meta.pmid,
                    e,
                )
            else:
                if resolved:
                    pmcid = resolved
                    meta.pmcid = resolved  # manifest 기록에도 반영

        ref = PaperRef(
            doi=meta.doi,
            pmid=meta.pmid or None,
            pmcid=pmcid,
        )
        result = fetch_chain(ref, chain)
        meta.fulltext_source = result.fulltext_source
        papers.append(PaperFull(meta=meta, sections=result.sections))

        if result.sections:
            indexed += 1
            sources[result.fulltext_source or "unknown"] += 1

        if i % FULLTEXT_PROGRESS_LOG_EVERY == 0 or i == total:
            elapsed = time.time() - started
            rate = i / elapsed if elapsed > 0 else 0.0
            eta_sec = (total - i) / rate if rate > 0 else 0.0
            src_summary = ", ".join(f"{k} {v}" for k, v in sorted(sources.items())) or "-"
            logger.info(
                "PMC 본문 수집 진행: %d/%d (%.1f편/s, 경과 %.0fs, ETA %.0fs, 확보 %d [%s], 미확보 %d)",
                i,
                total,
                rate,
                elapsed,
                eta_sec,
                indexed,
                src_summary,
                i - indexed,
            )
    return papers


def crawl_papers(
    *,
    queries: list[tuple[str, str, bool]] | None = None,
    max_per_category: int | None = None,
    max_total: int | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
    fetch_fulltext: bool = True,
    existing_dois: set[str] | None = None,
) -> list[PaperFull]:
    """65개 카테고리에 대해 OpenAlex 메인 + PubMed 보조 통합 검색.

    Task 10 흐름:
      1) 카테고리별 OpenAlex + PubMed 병렬 검색 → PaperMeta
      2) 카테고리 내부에서 DOI 기준 merge (OpenAlex 메타 우선, PubMed가 pmid/publication_types 보강)
      3) round-robin으로 카테고리 다양성 보존하며 max_total cap
      4) evidence_weight를 publication_types에서 calculate_evidence_weight()로 산출
      5) cascading fulltext (PMC → Europe PMC) 적용

    Args:
        queries: (카테고리명, pubmed_query, strict) 튜플 리스트.
            strict=True면 PubMed 보조 검색에 STRICT_PUBLICATION_FILTER 환경변수가
            True일 때만 strict 필터를 적용한다. 환경변수 False면 strict 인자 무시.
            None이면 SEARCH_QUERY_CATEGORIES를 (name, query, strict=True) 형태로 변환해 사용.
        max_per_category: 카테고리당 검색 상한. 지정하면 OpenAlex/PubMed 양쪽 cap을 override.
            None이면 OPENALEX_MAX_PER_CATEGORY / PUBMED_MAX_PER_CATEGORY 기본값 사용.
        max_total: 전체 DOI 수집 상한 (카테고리 다양성 유지하며 cap).
        min_date / max_date: PubMed pdat 필터 (YYYY/MM/DD).
        fetch_fulltext: cascading fulltext 수집 여부 (테스트에서 False로 끔).
        existing_dois: 이미 수집된 DOI 집합 (중복 방지).

    Returns:
        PaperFull 리스트. 각 PaperMeta는 search_categories + evidence_weight + fulltext_source 부여됨.
    """
    if queries is None:
        # 3-튜플 (name, query, filter_level) → 2-튜플 + strict bool 변환.
        # 기존 SEARCH_QUERY_CATEGORIES의 filter_level은 strict/semi/loose가 있지만,
        # Task 10에서는 strict 토글로 단일화 — strict 의도가 있는 카테고리만 True.
        queries = [(name, query, level != "loose") for name, query, level in SEARCH_QUERY_CATEGORIES]
    openalex_max = max_per_category if max_per_category is not None else OPENALEX_MAX_PER_CATEGORY
    pubmed_max = max_per_category if max_per_category is not None else PUBMED_MAX_PER_CATEGORY
    max_total = max_total or MAX_PAPERS_PER_RUN
    existing = existing_dois or set()

    publication_filter = get_publication_filter()

    per_category: list[tuple[str, list[PaperMeta]]] = []
    for name, pubmed_query, strict in queries:
        # OpenAlex 메인 검색
        try:
            openalex_results = search_openalex_by_category(
                name,
                max_results=openalex_max,
            )
        except Exception as e:
            logger.warning("OpenAlex 카테고리 '%s' 검색 실패: %s", name, e)
            openalex_results = []

        # PubMed 보조 검색 (publication_types + PMID 보강)
        full_query = pubmed_query + (publication_filter if strict else "")
        try:
            pmids = search_pmids(full_query, pubmed_max, min_date, max_date)
            pubmed_metas = fetch_paper_metadata(pmids) if pmids else []
        except Exception as e:
            logger.warning("PubMed 카테고리 '%s' 검색 실패: %s", name, e)
            pubmed_metas = []

        # 카테고리 내부 DOI merge (OpenAlex 우선 + PubMed 보강)
        cat_metas = _merge_by_doi(openalex_results, pubmed_metas)
        per_category.append((name, cat_metas))
        logger.info(
            "카테고리 '%s' 통합: OpenAlex %d + PubMed %d → %d (DOI dedup)",
            name,
            len(openalex_results),
            len(pubmed_metas),
            len(cat_metas),
        )

    # round-robin dedup + cap (DOI primary key)
    doi_order, doi_to_categories, doi_to_meta = _round_robin_dedup_metas(
        per_category,
        existing,
        max_total,
    )

    if not doi_to_meta:
        logger.info("모든 카테고리에서 신규 paper 없음")
        return []

    # search_categories + evidence_weight 부여
    for doi, meta in doi_to_meta.items():
        meta.search_categories = sorted(doi_to_categories[doi])
        meta.evidence_weight = calculate_evidence_weight(meta.publication_types)

    logger.info(
        "round-robin 결과: 신규 %d papers (평균 %.1f카테고리/논문)",
        len(doi_to_meta),
        sum(len(v) for v in doi_to_categories.values()) / len(doi_to_meta),
    )

    if fetch_fulltext:
        ordered_metas = [doi_to_meta[d] for d in doi_order]
        papers = _attach_fulltext(ordered_metas)
    else:
        papers = [PaperFull(meta=doi_to_meta[d], sections=[]) for d in doi_order]

    indexed_count = sum(1 for p in papers if p.sections)
    logger.info(
        "크롤링 완료: %d papers (본문 확보 %d, 본문 미확보 %d)",
        len(papers),
        indexed_count,
        len(papers) - indexed_count,
    )
    return papers
